#!/usr/bin/env python3
"""Translate prd-bench-local-runner's results.json into Harbor's reward.json.

Input shape (from prd_bench_local_runner.results.BenchmarkResults.save):
    {
      "total": int, "passed": int, "failed": int,
      "errors": int, "skipped": int,
      "duration_seconds": float,
      "tests": [ {name, file, status, ...}, ... ]
    }

Output shape: **single-key** flat dict, because Harbor's default aggregate
metric (`harbor.metrics.mean.Mean.compute`) raises ValueError on multi-key
reward dicts ("Expected exactly one key in reward dictionary"). We emit just:

    {"reward": <pass_rate>}                  # 0.0 .. 1.0

Per-test breakdown / counts are preserved in `/logs/verifier/results.json`
(copied by test.sh) for human inspection — they live alongside reward.json
in the trial output.

A missing or malformed results.json produces a zero reward with a note in
stderr — we never crash; Harbor must always read a valid reward.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def zero(reason: str) -> dict:
    print(f"[results_to_reward] {reason}", file=sys.stderr)
    return {"reward": 0.0}


def convert(path: Path) -> dict:
    if not path.exists():
        return zero(f"results.json not found: {path}")
    try:
        d = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return zero(f"results.json malformed: {exc}")

    total = int(d.get("total", 0))
    passed = int(d.get("passed", 0))
    rate = (passed / total) if total > 0 else 0.0
    return {"reward": rate}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: results_to_reward.py <results.json>", file=sys.stderr)
        return 2
    json.dump(convert(Path(argv[1])), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
