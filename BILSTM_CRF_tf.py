import math
import helper
import numpy as np
import tensorflow as tf

class BILSTM_CRF(object):
    
    def __init__(self, num_chars, num_poses, num_dises, num_classes, num_steps=200, num_epochs=100, embedding_matrix=None, is_training=True, is_crf=True, weight=False):
        # Parameter
        self.max_f1 = 0
        self.learning_rate = 0.002
        self.dropout_rate = 0.5
        self.batch_size = 64
        self.num_layers = 1   
        self.emb_dim = 50 #char, left, right, rel
        self.pos_dim = 25 #pos, lpos, rpos
        self.dis_dim = 25 #dis
        self.hidden_dim = 300
        self.filter_sizes = [3]
        self.num_epochs = num_epochs
        self.num_steps = num_steps
        self.num_chars = num_chars
        self.num_poses = num_poses
        self.num_dises = num_dises
        self.num_classes = num_classes
        
        # placeholder of x, x_pos, y
        self.inputs = tf.placeholder(tf.int32, [None, self.num_steps])
        self.lefts = tf.placeholder(tf.int32, [None, self.num_steps])
        self.rights = tf.placeholder(tf.int32, [None, self.num_steps])
        self.poses = tf.placeholder(tf.int32, [None, self.num_steps])
        self.lposes = tf.placeholder(tf.int32, [None, self.num_steps])
        self.rposes = tf.placeholder(tf.int32, [None, self.num_steps])
        self.rels = tf.placeholder(tf.int32, [None, self.num_steps])
        self.dises = tf.placeholder(tf.int32, [None, self.num_steps])
        self.targets = tf.placeholder(tf.int32, [None, self.num_steps])
        self.targets_transition = tf.placeholder(tf.int32, [None])
        
        # char embedding
        if embedding_matrix != None:
            self.embedding = tf.Variable(embedding_matrix, trainable=False, name="emb", dtype=tf.float32)
        else:
            self.embedding = tf.get_variable("emb", [self.num_chars, self.emb_dim])

        self.inputs_emb = tf.nn.embedding_lookup(self.embedding, self.inputs)
        self.lefts_emb = tf.nn.embedding_lookup(self.embedding, self.lefts)
        self.rights_emb = tf.nn.embedding_lookup(self.embedding, self.rights)
        self.rels_emb = tf.nn.embedding_lookup(self.embedding, self.rels)

        #pos embedding
        self.pos_embedding = tf.get_variable("pos_embedding", [self.num_poses, self.pos_dim])
        
        self.pos_emb = tf.nn.embedding_lookup(self.pos_embedding, self.poses)
        self.lpos_emb = tf.nn.embedding_lookup(self.pos_embedding, self.lposes)
        self.rpos_emb = tf.nn.embedding_lookup(self.pos_embedding, self.rposes)

        self.dis_embedding = tf.get_variable("dis_embedding", [self.num_dises, self.dis_dim])
        self.dis_emb = tf.nn.embedding_lookup(self.dis_embedding, self.dises)

        #nonlinear layer
        self.inputs_emb = tf.concat([self.inputs_emb, 
            self.pos_emb, self.rels_emb, self.dis_emb], axis=2)
        self.inputs_emb = tf.tanh(self.inputs_emb)

        # lstm cell
        lstm_cell_fw = tf.nn.rnn_cell.BasicLSTMCell(self.hidden_dim)
        lstm_cell_bw = tf.nn.rnn_cell.BasicLSTMCell(self.hidden_dim)

        # dropout
        if is_training:
            lstm_cell_fw = tf.nn.rnn_cell.DropoutWrapper(lstm_cell_fw, output_keep_prob=(1 - self.dropout_rate))
            lstm_cell_bw = tf.nn.rnn_cell.DropoutWrapper(lstm_cell_bw, output_keep_prob=(1 - self.dropout_rate))

        lstm_cell_fw = tf.nn.rnn_cell.MultiRNNCell([lstm_cell_fw] * self.num_layers)
        lstm_cell_bw = tf.nn.rnn_cell.MultiRNNCell([lstm_cell_bw] * self.num_layers)

        # get the length of each sample
        self.length = tf.reduce_sum(tf.sign(self.inputs), axis=1)
        self.length = tf.cast(self.length, tf.int32)  
        
        # forward and backward
        self.outputs, _ = tf.nn.bidirectional_dynamic_rnn(
            lstm_cell_fw, 
            lstm_cell_bw,
            self.inputs_emb, 
            dtype=tf.float32,
            sequence_length=self.length
        )
        
        # softmax
        self.outputs = tf.reshape(tf.concat(axis=2, values=self.outputs), [-1, self.hidden_dim * 2])
        self.softmax_w = tf.get_variable("softmax_w", [self.hidden_dim * 2, self.num_classes])
        self.softmax_b = tf.get_variable("softmax_b", [self.num_classes])
        self.logits = tf.matmul(self.outputs, self.softmax_w) + self.softmax_b
        self.logits = tf.reshape(self.logits, [self.batch_size, self.num_steps, self.num_classes])

        if not is_crf:
            self.tags_scores = tf.reshape(self.logits, [self.batch_size, self.num_steps, self.num_classes])
        else:
            log_likelihood, trans_params = tf.contrib.crf.crf_log_likelihood(
                    self.logits, self.targets, self.length)
            self.trans_params = trans_params # need to evaluate it for decoding
            self.loss = tf.reduce_mean(-log_likelihood)
        
        # summary
        self.train_summary = tf.summary.scalar("loss", self.loss)
        self.val_summary = tf.summary.scalar("loss", self.loss)        
        
        self.optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate).minimize(self.loss) 

    def logsumexp(self, x, axis=None):
        x_max = tf.reduce_max(x, axis=axis, keep_dims=True)
        x_max_ = tf.reduce_max(x, axis=axis)
        return x_max_ + tf.log(tf.reduce_sum(tf.exp(x - x_max), axis=axis))  

    def train(self, sess, save_file, train_data, val_data):
        saver = tf.train.Saver(max_to_keep=3)

        X_train = train_data['char']
        X_left_train = train_data['left']
        X_right_train = train_data['right']
        X_pos_train = train_data['pos']
        X_lpos_train = train_data['lpos']
        X_rpos_train = train_data['rpos']
        X_rel_train = train_data['rel']
        X_dis_train = train_data['dis']
        y_train = train_data['label']

        X_val = val_data['char']
        X_left_val = val_data['left']
        X_right_val = val_data['right']
        X_pos_val = val_data['pos']
        X_lpos_val = val_data['lpos']
        X_rpos_val = val_data['rpos']
        X_rel_val = val_data['rel']
        X_dis_val = val_data['dis']
        y_val = val_data['label']

        char2id, id2char = helper.loadMap("char2id")
        pos2id, id2pos = helper.loadMap("pos2id")
        label2id, id2label = helper.loadMap("label2id")

        merged = tf.summary.merge_all()
        summary_writer_train = tf.summary.FileWriter('loss_log/train_loss', sess.graph)  
        summary_writer_val = tf.summary.FileWriter('loss_log/val_loss', sess.graph)     
        
        num_iterations = int(math.ceil(1.0 * len(X_train) / self.batch_size))

        cnt = 0
        for epoch in range(self.num_epochs):
            # shuffle train in each epoch
            sh_index = np.arange(len(X_train))
            np.random.shuffle(sh_index)
            X_train = X_train[sh_index]
            X_left_train = X_left_train[sh_index]
            X_right_train = X_right_train[sh_index]
            X_pos_train = X_pos_train[sh_index]
            X_lpos_train = X_lpos_train[sh_index]
            X_rpos_train = X_rpos_train[sh_index]
            X_rel_train = X_rel_train[sh_index]
            X_dis_train = X_dis_train[sh_index]
            y_train = y_train[sh_index]

            train_data['char'] = X_train
            train_data['left'] = X_left_train
            train_data['right'] = X_right_train
            train_data['pos'] = X_pos_train
            train_data['lpos'] = X_lpos_train
            train_data['rpos'] = X_rpos_train
            train_data['rel'] = X_rel_train
            train_data['dis'] = X_dis_train
            train_data['label'] = y_train

            print "current epoch: %d" % (epoch)
            for iteration in range(num_iterations):
                # train
                train_batches = helper.nextBatch(train_data, start_index=iteration * self.batch_size, batch_size=self.batch_size)
                X_train_batch = train_batches['char']
                X_left_train_batch = train_batches['left']
                X_right_train_batch = train_batches['right']
                X_pos_train_batch = train_batches['pos']
                X_lpos_train_batch = train_batches['lpos']
                X_rpos_train_batch = train_batches['rpos']
                X_rel_train_batch = train_batches['rel']
                X_dis_train_batch = train_batches['dis']
                y_train_batch = train_batches['label']
                # y_train_weight_batch = 1 + np.array((y_train_batch == label2id['B']) | (y_train_batch == label2id['E']), float)
                transition_batch = helper.getTransition(y_train_batch, self.num_classes)
                
                _, loss_train, length, train_summary, logits, trans_params =\
                    sess.run([
                        self.optimizer, 
                        self.loss, 
                        self.length,
                        self.train_summary,
                        self.logits,
                        self.trans_params,
                    ], 
                    feed_dict={
                        self.targets_transition:transition_batch, 
                        self.inputs:X_train_batch,
                        self.lefts:X_left_train_batch,
                        self.rights:X_right_train_batch,
                        self.poses:X_pos_train_batch,
                        self.lposes:X_lpos_train_batch,
                        self.rposes:X_rpos_train_batch,
                        self.rels:X_rel_train_batch,
                        self.dises:X_dis_train_batch,
                        self.targets:y_train_batch 
                        # self.targets_weight:y_train_weight_batch
                    })
                # print (len(length))

                predicts_train = self.viterbi(logits, trans_params, length, predict_size=self.batch_size)
                if iteration > 0 and iteration % 10 == 0:
                    cnt += 1
                    hit_num, pred_num, true_num = self.evaluate(y_train_batch, predicts_train, id2char, id2label)
                    precision_train, recall_train, f1_train = self.caculate(hit_num, pred_num, true_num)
                    summary_writer_train.add_summary(train_summary, cnt)
                    print "iteration: %5d/%5d, train loss: %5d, train precision: %.5f, train recall: %.5f, train f1: %.5f" % (iteration, num_iterations, loss_train, precision_train, recall_train, f1_train)  
                    
                # validation
                if iteration > 0 and iteration % 100 == 0:
                    val_batches = helper.nextRandomBatch(val_data, batch_size=self.batch_size)
                    
                    X_val_batch = val_batches['char']
                    X_left_val_batch = val_batches['left']
                    X_right_val_batch = val_batches['right']
                    X_pos_val_batch = val_batches['pos']
                    X_lpos_val_batch = val_batches['lpos']
                    X_rpos_val_batch = val_batches['rpos']
                    X_rel_val_batch = val_batches['rel']
                    X_dis_val_batch = val_batches['dis']
                    y_val_batch = val_batches['label']
                    
                    # y_val_weight_batch = 1 + np.array((y_val_batch == label2id['B']) | (y_val_batch == label2id['E']), float)
                    transition_batch = helper.getTransition(y_val_batch, self.num_classes)
                    
                    loss_val, length, val_summary, logits, trans_params =\
                        sess.run([
                            self.loss, 
                            self.length,
                            self.val_summary,
                            self.logits,
                            self.trans_params,
                        ], 
                        feed_dict={
                            self.targets_transition:transition_batch, 
                            self.inputs:X_val_batch,
                            self.lefts:X_left_val_batch,
                            self.rights:X_right_val_batch,
                            self.poses:X_pos_val_batch,
                            self.lposes:X_lpos_val_batch,
                            self.rposes:X_rpos_val_batch,
                            self.rels:X_rel_val_batch,
                            self.dises:X_dis_val_batch,
                            self.targets:y_val_batch 
                            # self.targets_weight:y_val_weight_batch
                        })
                    
                    predicts_val = self.viterbi(logits, trans_params, length, predict_size=self.batch_size)
                    hit_num, pred_num, true_num = self.evaluate(y_val_batch, predicts_val, id2char, id2label)
                    precision_val, recall_val, f1_val = self.caculate(hit_num, pred_num, true_num)
                    summary_writer_val.add_summary(val_summary, cnt)
                    print "iteration: %5d, valid loss: %5d, valid precision: %.5f, valid recall: %.5f, valid f1: %.5f" % (iteration, loss_val, precision_val, recall_val, f1_val)

                if epoch > 0 and iteration == num_iterations -1:
                    num_val_iterations = int(math.ceil(1.0 * len(X_val) / self.batch_size))
                    preds_lines = []
                    for val_iteration in range(num_val_iterations):
                        val_batches = helper.nextBatch(val_data, start_index=val_iteration * self.batch_size, batch_size=self.batch_size)
                        X_val_batch = val_batches['char']
                        X_left_val_batch = val_batches['left']
                        X_right_val_batch = val_batches['right']
                        X_pos_val_batch = val_batches['pos']
                        X_lpos_val_batch = val_batches['lpos']
                        X_rpos_val_batch = val_batches['rpos']
                        X_rel_val_batch = val_batches['rel']
                        X_dis_val_batch = val_batches['dis']
                        y_val_batch = val_batches['label']

                        # y_val_weight_batch = 1 + np.array((y_val_batch == label2id['B']) | (y_val_batch == label2id['E']), float)
                        transition_batch = helper.getTransition(y_val_batch, self.num_classes)
                        loss_val, length, val_summary, logits, trans_params =\
                            sess.run([
                                self.loss, 
                                self.length,
                                self.val_summary,
                                self.logits,
                                self.trans_params,
                            ], 
                            feed_dict={
                                self.targets_transition:transition_batch, 
                                self.inputs:X_val_batch,
                                self.lefts:X_left_val_batch,
                                self.rights:X_right_val_batch,
                                self.poses:X_pos_val_batch,
                                self.lposes:X_lpos_val_batch,
                                self.rposes:X_rpos_val_batch,
                                self.rels:X_rel_val_batch,
                                self.dises:X_dis_val_batch,
                                self.targets:y_val_batch 
                                # self.targets_weight:y_val_weight_batch
                            })
                    
                        predicts_val = self.viterbi(logits, trans_params, length, predict_size=self.batch_size)
                        preds_lines.extend(predicts_val)
                    preds_lines = preds_lines[:len(y_val)]
                    recall_val, precision_val, f1_val, errors = helper.calc_f1(preds_lines, id2label, 'cpbdev.txt', 'validation.out')
                    if f1_val > self.max_f1:
                        self.max_f1 = f1_val
                        save_path = saver.save(sess, save_file + '/model.ckpt', global_step=iteration)
                        helper.calc_f1(preds_lines, id2label, 'cpbdev.txt', 'validation.out.best')
                        print "saved the best model with f1: %.5f" % (self.max_f1)
                    print "valid precision: %.5f, valid recall: %.5f, valid f1: %.5f, errors: %5d" % (precision_val, recall_val, f1_val, errors)



    def test(self, sess, test_data, output_path):
        X_test = test_data['char']
        X_left_test = test_data['left']
        X_right_test = test_data['right']
        X_pos_test = test_data['pos']
        X_lpos_test = test_data['lpos']
        X_rpos_test = test_data['rpos']
        X_rel_test = test_data['rel']
        X_dis_test = test_data['dis']

        char2id, id2char = helper.loadMap("char2id")
        pos2id, id2pos = helper.loadMap("pos2id")
        label2id, id2label = helper.loadMap("label2id")
        num_iterations = int(math.ceil(1.0 * len(X_test) / self.batch_size))
        print "number of iteration: " + str(num_iterations)
        with open(output_path, "wb") as outfile:
            pred_lines = []
            for i in range(num_iterations):
                print "iteration: " + str(i + 1)
                results = []
                X_test_batch = X_test[i * self.batch_size : (i + 1) * self.batch_size]
                X_left_test_batch = X_left_test[i * self.batch_size : (i + 1) * self.batch_size]
                X_right_test_batch = X_right_test[i * self.batch_size : (i + 1) * self.batch_size]
                X_pos_test_batch = X_pos_test[i * self.batch_size : (i + 1) * self.batch_size]
                X_lpos_test_batch = X_lpos_test[i * self.batch_size : (i + 1) * self.batch_size]
                X_rpos_test_batch = X_rpos_test[i * self.batch_size : (i + 1) * self.batch_size]
                X_rel_test_batch = X_rel_test[i * self.batch_size : (i + 1) * self.batch_size]
                X_dis_test_batch = X_dis_test[i * self.batch_size : (i + 1) * self.batch_size]
                if i == num_iterations - 1 and len(X_test_batch) < self.batch_size:
                    X_test_batch = list(X_test_batch)
                    X_left_test_batch = list(X_left_test_batch)
                    X_right_test_batch = list(X_right_test_batch)
                    X_pos_test_batch = list(X_pos_test_batch)
                    X_lpos_test_batch = list(X_lpos_test_batch)
                    X_rpos_test_batch = list(X_rpos_test_batch)
                    X_rel_test_batch = list(X_rel_test_batch)
                    X_dis_test_batch = list(X_dis_test_batch)
                    
                    last_size = len(X_test_batch)

                    X_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    X_left_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    X_right_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    X_pos_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    X_lpos_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    X_rpos_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    X_rel_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    X_dis_test_batch += [[0 for j in range(self.num_steps)] for i in range(self.batch_size - last_size)]
                    
                    X_test_batch = np.array(X_test_batch)
                    X_left_test_batch = np.array(X_left_test_batch)
                    X_right_test_batch = np.array(X_right_test_batch)
                    X_pos_test_batch = np.array(X_pos_test_batch) 
                    X_lpos_test_batch = np.array(X_lpos_test_batch)
                    X_rpos_test_batch = np.array(X_rpos_test_batch)
                    X_rel_test_batch = np.array(X_rel_test_batch)
                    X_dis_test_batch = np.array(X_dis_test_batch)

                    test_batches = {}
                    test_batches['char'] = X_test_batch
                    test_batches['left'] = X_left_test_batch
                    test_batches['right'] = X_right_test_batch
                    test_batches['pos'] = X_pos_test_batch
                    test_batches['lpos'] = X_lpos_test_batch
                    test_batches['rpos'] = X_rpos_test_batch
                    test_batches['rel'] = X_rel_test_batch
                    test_batches['dis'] = X_dis_test_batch
                    results = self.predictBatch(sess, test_batches, id2label)
                    results = results[:last_size]
                    pred_lines.extend(results)
                else:
                    X_test_batch = np.array(X_test_batch)
                    X_left_test_batch = np.array(X_left_test_batch)
                    X_right_test_batch = np.array(X_right_test_batch)
                    X_pos_test_batch = np.array(X_pos_test_batch) 
                    X_lpos_test_batch = np.array(X_lpos_test_batch)
                    X_rpos_test_batch = np.array(X_rpos_test_batch)
                    X_rel_test_batch = np.array(X_rel_test_batch)
                    X_dis_test_batch = np.array(X_dis_test_batch)

                    test_batches = {}
                    test_batches['char'] = X_test_batch
                    test_batches['left'] = X_left_test_batch
                    test_batches['right'] = X_right_test_batch
                    test_batches['pos'] = X_pos_test_batch
                    test_batches['lpos'] = X_lpos_test_batch
                    test_batches['rpos'] = X_rpos_test_batch
                    test_batches['rel'] = X_rel_test_batch
                    test_batches['dis'] = X_dis_test_batch
                    
                    results = self.predictBatch(sess, test_batches, id2label)
                    pred_lines.extend(results)
            return pred_lines
    def viterbi(self, logits, trans_params, lengths, predict_size=128):
        # best_paths = []
        # for m in range(predict_size):
        #     path = []
        #     last_max_node = np.argmax(max_scores[m][length[m]])
        #     # last_max_node = 0
        #     for t in range(1, length[m] + 1)[::-1]:
        #         last_max_node = max_scores_pre[m][t][last_max_node]
        #         path.append(last_max_node)
        #     path = path[::-1]
        #     best_paths.append(path)
        # return best_paths
        viterbi_sequences = []

        # iterate over the sentences because no batching in vitervi_decode

        for logit, sequence_length in zip(logits, lengths):
            if sequence_length == 0:
                viterbi_sequences += [[]]
                continue
            logit = logit[:sequence_length] # keep only the valid steps
            viterbi_seq, viterbi_score = tf.contrib.crf.viterbi_decode(
                    logit, trans_params)
            viterbi_sequences += [viterbi_seq]
        return viterbi_sequences

    def predictBatch(self, sess, batches, id2label):
        results = []
        
        X = batches['char']
        X_left = batches['left']
        X_right = batches['right']
        X_pos = batches['pos']
        X_lpos = batches['lpos']
        X_rpos = batches['rpos']
        X_rel = batches['rel']
        X_dis = batches['dis']
        
        length, logits, trans_params = sess.run([self.length, self.logits, self.trans_params], 
            feed_dict={
                self.inputs:X,
                self.lefts:X_left,
                self.rights:X_right,
                self.poses:X_pos,
                self.lposes:X_lpos,
                self.rposes:X_rpos,
                self.rels:X_rel,
                self.dises:X_dis
            })
        predicts = self.viterbi(logits, trans_params, length, self.batch_size)
        for i in range(len(predicts)):
            y_pred = [id2label[val] for val in predicts[i]]
            results.append(y_pred)
        return results

    def evaluate(self, y_true, y_pred,id2char, id2label):
        hit_num = 0
        pred_num = 0
        true_num = 0
        for i in range(len(y_true)):
            # print (y_true[i])
            # print (y_pred[i])
            y = [str(id2label[val].encode("utf-8")) for val in y_true[i]]
            y_hat = [str(id2label[val].encode("utf-8")) for val in y_pred[i]]
            for t in range(len(y_hat)):
                if y[t] == y_hat[t] and y_hat[t] != 'O':
                    hit_num += 1 
                if y_hat[t] != '<PAD>' and y_hat[t] != 'O':
                    pred_num += 1
                if y[t] != '<PAD>' and y[t] != 'O':
                    true_num +=1 
        return hit_num, pred_num, true_num 

    def caculate(self, hit_num, pred_num, true_num):
        precision = -1.0;
        recall = -1.0
        f1 = -1.0
        if pred_num != 0:
            precision = 1.0 * hit_num / pred_num
        if true_num != 0:
            recall = 1.0 * hit_num / true_num
        if precision > 0 and recall > 0:
            f1 = 2.0 * (precision * recall) / (precision + recall)
        return precision, recall, f1