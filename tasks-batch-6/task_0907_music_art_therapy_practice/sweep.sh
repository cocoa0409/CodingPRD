#!/usr/bin/env bash
cd /home/ubuntu/github/CodingPRD/tasks/task_0907_music_art_therapy_practice
rm -f workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_0907_music_art_therapy_practice/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_0907_music_art_therapy_practice/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   workspace/implementation/results.${i}.json &
done
wait
