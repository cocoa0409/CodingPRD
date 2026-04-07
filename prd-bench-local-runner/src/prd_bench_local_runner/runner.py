"""
BenchmarkRunner: main orchestrator tying lifecycle management and test execution together.

Usage:
    runner = BenchmarkRunner(
        start_command="cd impl && python app.py",
        test_dir="./test_suite",
    )
    results = runner.run()
"""

import time
from typing import Optional

from .lifecycle import ServerLifecycleManager
from .executor import TestExecutor
from .results import BenchmarkResults


class BenchmarkRunner:
    def __init__(
        self,
        start_command: Optional[str] = None,
        test_dir: str = "./test_suite",
        api_url: str = "http://localhost:10000",
        startup_timeout: float = 30.0,
        per_test_timeout: int = 10,
        results_file: Optional[str] = None,
        skip_lifecycle: bool = False,
    ):
        self.start_command = start_command
        self.test_dir = test_dir
        self.api_url = api_url
        self.startup_timeout = startup_timeout
        self.per_test_timeout = per_test_timeout
        self.results_file = results_file
        self.skip_lifecycle = skip_lifecycle

        if not skip_lifecycle and not start_command:
            raise ValueError("start_command is required unless skip_lifecycle=True")

    def run(self) -> BenchmarkResults:
        """Run the full benchmark: start server → run tests → stop server → return results."""
        lifecycle = None
        start_time = time.time()

        try:
            # Start server
            if not self.skip_lifecycle:
                lifecycle = ServerLifecycleManager(
                    start_command=self.start_command,
                    api_url=self.api_url,
                    startup_timeout=self.startup_timeout,
                )
                lifecycle.start()

            # Run tests
            executor = TestExecutor(
                test_dir=self.test_dir,
                api_url=self.api_url,
                per_test_timeout=self.per_test_timeout,
                results_file=self.results_file,
                skip_lifecycle=self.skip_lifecycle,
                start_command=self.start_command,
            )
            results = executor.run()

        finally:
            # Always stop server
            if lifecycle:
                lifecycle.stop()

        results.duration_seconds = time.time() - start_time

        if self.results_file:
            results.save(self.results_file)

        return results
