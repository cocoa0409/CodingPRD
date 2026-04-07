"""CLI entry point for the Docker benchmark runner."""

import argparse
import sys
from pathlib import Path

from loguru import logger

from .config import RunConfig
from .runner import DockerBenchmarkRunner


def main():
    parser = argparse.ArgumentParser(
        description="Docker-based benchmark runner for API compliance testing",
    )
    parser.add_argument(
        "--task-dir",
        required=True,
        help="Path to task directory (contains test_suite/, test_helpers/, Dockerfile.test)",
    )
    parser.add_argument(
        "--impl-dir",
        required=True,
        help="Path to implementation directory (contains Dockerfile + source code)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=10000,
        help="Port the implementation listens on (default: 10000)",
    )
    parser.add_argument(
        "--build-timeout",
        type=int,
        default=300,
        help="Docker image build timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--startup-timeout",
        type=int,
        default=60,
        help="Implementation startup timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--test-timeout",
        type=int,
        default=600,
        help="Test execution timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--results-file",
        help="Path to write results JSON",
    )
    parser.add_argument(
        "--run-id",
        help="Unique run identifier for Docker resource naming (auto-generated if omitted)",
    )
    parser.add_argument(
        "--runner-source-dir",
        help="Path to prd-bench-local-runner/ source (auto-detected if omitted)",
    )
    parser.add_argument(
        "--keep-containers",
        action="store_true",
        help="Do not remove Docker resources after run (for debugging)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level=args.log_level)

    results_file = args.results_file

    config_kwargs = dict(
        task_dir=Path(args.task_dir),
        impl_dir=Path(args.impl_dir),
        port=args.port,
        build_timeout=args.build_timeout,
        startup_timeout=args.startup_timeout,
        test_timeout=args.test_timeout,
        results_file=Path(results_file) if results_file else None,
        keep_containers=args.keep_containers,
        log_level=args.log_level,
    )
    if args.run_id:
        config_kwargs["run_id"] = args.run_id
    if args.runner_source_dir:
        config_kwargs["runner_source_dir"] = Path(args.runner_source_dir)

    config = RunConfig(**config_kwargs)
    runner = DockerBenchmarkRunner(config)
    results = runner.run()

    has_failures = results.failed > 0 or results.errors > 0
    sys.exit(1 if has_failures else 0)


if __name__ == "__main__":
    main()
