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

from .results import BenchmarkResults


class TestExecutor:
    def __init__(
        self,
        test_dir: str,
        api_url: str = "http://localhost:3000",
        per_test_timeout: int = 10,
        results_file: Optional[str] = None,
        skip_lifecycle: bool = False,
        start_command: Optional[str] = None,
    ):
        self.test_dir = os.path.abspath(test_dir)
        self.api_url = api_url
        self.per_test_timeout = per_test_timeout
        self.results_file = results_file
        self.skip_lifecycle = skip_lifecycle
        self.start_command = start_command or ""

    def run(self) -> BenchmarkResults:
        """Run pytest and return structured results."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            junit_path = os.path.join(tmp_dir, "results.xml")

            cmd = self._build_command(junit_path)
            env = self._build_env()

            print(f"[executor] Running: {' '.join(cmd)}")
            print(f"[executor] Test dir: {self.test_dir}")

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
            "-p", "prd_bench_runner.pytest_plugin",
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

        # Ensure the prd_bench_runner package is importable by the pytest subprocess
        runner_src = str(Path(__file__).parent.parent)
        python_path = env.get("PYTHONPATH", "")
        if runner_src not in python_path:
            env["PYTHONPATH"] = f"{runner_src}:{python_path}" if python_path else runner_src

        return env
