"""CLI entry point for prd-bench-local-run."""

import argparse
import sys

from loguru import logger

from .runner import BenchmarkRunner


def main():
    parser = argparse.ArgumentParser(
        prog="prd-bench-local-run",
        description="Run benchmark tests against an API server with automatic lifecycle management.",
    )
    parser.add_argument(
        "--start-command",
        help='Command to start the API server (e.g., "cd impl && python app.py")',
    )
    parser.add_argument(
        "--test-dir",
        required=True,
        help="Path to the pytest test directory (test_suite/)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:10000",
        help="API server URL (default: http://localhost:10000)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Server startup timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--test-timeout",
        type=int,
        default=10,
        help="Per-test timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--results-file",
        help="Output JSON results file path",
    )
    parser.add_argument(
        "--skip-lifecycle",
        action="store_true",
        help="Skip server start/stop (server already running externally)",
    )
    parser.add_argument(
        "--isolation",
        default="none",
        choices=["none", "per-test-server"],
        help=(
            "Isolation mode. 'per-test-server' restarts the API server before "
            "each pytest test while keeping one pytest process (default: none)"
        ),
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

    if not args.skip_lifecycle and not args.start_command:
        parser.error("--start-command is required unless --skip-lifecycle is set")
    if args.skip_lifecycle and args.isolation != "none":
        parser.error("--isolation requires lifecycle management; do not use it with --skip-lifecycle")

    runner = BenchmarkRunner(
        start_command=args.start_command,
        test_dir=args.test_dir,
        api_url=args.api_url,
        startup_timeout=args.timeout,
        per_test_timeout=args.test_timeout,
        results_file=args.results_file,
        skip_lifecycle=args.skip_lifecycle,
        isolation=args.isolation,
    )

    results = runner.run()

    logger.info(f"Results: {results.passed}/{results.total} passed, "
                f"{results.failed} failed, {results.errors} errors, "
                f"{results.skipped} skipped")
    logger.info(f"Duration: {results.duration_seconds:.1f}s")

    if results.failed > 0 or results.errors > 0:
        failed_tests = [t for t in results.tests if t.status in ("failed", "error")]
        for t in failed_tests[:20]:
            first_line = (t.error_message or "").strip().split("\n")[0][:120]
            logger.error(f"FAIL {t.name}: {first_line}")
        if len(failed_tests) > 20:
            logger.error(f"... and {len(failed_tests) - 20} more")

    sys.exit(0 if results.failed == 0 and results.errors == 0 else 1)


if __name__ == "__main__":
    main()
