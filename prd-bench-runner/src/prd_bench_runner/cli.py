"""CLI entry point for prd-bench-run."""

import argparse
import sys

from .runner import BenchmarkRunner


def main():
    parser = argparse.ArgumentParser(
        prog="prd-bench-run",
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
        default="http://localhost:3000",
        help="API server URL (default: http://localhost:3000)",
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

    args = parser.parse_args()

    if not args.skip_lifecycle and not args.start_command:
        parser.error("--start-command is required unless --skip-lifecycle is set")

    runner = BenchmarkRunner(
        start_command=args.start_command,
        test_dir=args.test_dir,
        api_url=args.api_url,
        startup_timeout=args.timeout,
        per_test_timeout=args.test_timeout,
        results_file=args.results_file,
        skip_lifecycle=args.skip_lifecycle,
    )

    results = runner.run()

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Results: {results.passed}/{results.total} passed, "
          f"{results.failed} failed, {results.errors} errors, "
          f"{results.skipped} skipped")
    print(f"Duration: {results.duration_seconds:.1f}s")
    print(f"{'=' * 60}")

    if results.failed > 0 or results.errors > 0:
        print("\nFailed tests:")
        for t in results.tests:
            if t.status in ("failed", "error"):
                print(f"  FAIL {t.name}")
                if t.error_message:
                    # Show first line of error
                    first_line = t.error_message.strip().split("\n")[0]
                    print(f"       {first_line}")

    sys.exit(0 if results.failed == 0 and results.errors == 0 else 1)


if __name__ == "__main__":
    main()
