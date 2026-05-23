"""
Test executor: invoke pytest as subprocess, collect structured results.

Runs pytest on the test_suite directory, injects environment variables for
the server URL and lifecycle management, parses JUnit XML for results.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger

from .results import BenchmarkResults


class TestExecutor:
    def __init__(
        self,
        test_dir: str,
        api_url: str = "http://localhost:10000",
        per_test_timeout: int = 10,
        results_file: Optional[str] = None,
        skip_lifecycle: bool = False,
        start_command: Optional[str] = None,
        isolation: str = "none",
    ):
        self.test_dir = os.path.abspath(test_dir)
        self.api_url = api_url
        self.per_test_timeout = per_test_timeout
        self.results_file = results_file
        self.skip_lifecycle = skip_lifecycle
        self.start_command = start_command or ""
        self.isolation = isolation

    def run(self) -> BenchmarkResults:
        """Run pytest and return structured results."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            junit_path = os.path.join(tmp_dir, "results.xml")

            cmd = self._build_command(junit_path)
            env = self._build_env()

            logger.info(f"Running: {' '.join(cmd)}")
            logger.info(f"Test dir: {self.test_dir}")

            proc = subprocess.run(
                cmd,
                env=env,
                cwd=self.test_dir,
            )

            # Parse results
            if os.path.exists(junit_path):
                results = BenchmarkResults.from_junit_xml(junit_path)
            else:
                # pytest didn't produce XML — probably crashed
                results = BenchmarkResults(
                    total=0, errors=1,
                    tests=[],
                    duration_seconds=0,
                )

            if self.results_file:
                results.save(self.results_file)

            return results

    def _build_command(self, junit_path: str) -> list[str]:
        cmd = [
            sys.executable, "-m", "pytest",
            self.test_dir,
            "-p", "prd_bench_local_runner.pytest_plugin",
            f"--junitxml={junit_path}",
            "-v",
            "--tb=short",
        ]

        # Add per-test timeout if pytest-timeout is available
        try:
            import pytest_timeout  # noqa: F401
            cmd.append(f"--timeout={self.per_test_timeout}")
        except ImportError:
            pass

        return cmd

    def _build_env(self) -> dict[str, str]:
        """Build environment variables for the pytest subprocess."""
        env = {**os.environ}

        # For test_helpers/api_client.py
        env["API_BASE_URL"] = self.api_url

        # For pytest_plugin.py
        env["_PRD_BENCH_API_URL"] = self.api_url
        env["_PRD_BENCH_START_COMMAND"] = self.start_command
        env["_PRD_BENCH_SKIP_LIFECYCLE"] = "true" if self.skip_lifecycle else "false"
        env["_PRD_BENCH_ISOLATION"] = self.isolation

        # Add paths to PYTHONPATH:
        # 1. prd_bench_local_runner package (for pytest_plugin + testing utilities)
        # 2. Parent of test_dir (so `from test_helpers import ...` works)
        #
        # Compare against the colon-split list, not raw substring, otherwise
        # "/tests" gets silently dropped when "/tests/prd-bench-local-runner/src"
        # is already present.
        extra_paths = [
            str(Path(__file__).parent.parent),          # prd_bench_local_runner src
            str(Path(self.test_dir).parent.resolve()),  # parent of test_suite (contains test_helpers)
        ]
        existing = env.get("PYTHONPATH", "").split(":") if env.get("PYTHONPATH") else []
        for p in extra_paths:
            if p not in existing:
                existing.insert(0, p)
        env["PYTHONPATH"] = ":".join(existing)

        return env
