"""DockerBenchmarkRunner: top-level orchestrator."""

import time

from loguru import logger
from prd_bench_local_runner.results import BenchmarkResults, TestResult

from .config import RunConfig
from .docker_ops import DockerOperations
from .errors import (
    ImplBuildError,
    TestBuildError,
    ImplStartupError,
    ImplStartupTimeout,
    TestExecutionTimeout,
)
from .health import HealthChecker
from .results import collect_results

class DockerBenchmarkRunner:
    def __init__(self, config: RunConfig):
        self.config = config
        self.docker_ops = DockerOperations(config)
        self.health = HealthChecker(config, self.docker_ops)

    def run(self) -> BenchmarkResults:
        start_time = time.monotonic()

        # Validate inputs
        if not self.config.impl_dockerfile.exists():
            return self._error("validation", f"No Dockerfile at {self.config.impl_dockerfile}")
        if not self.config.test_dockerfile.exists():
            return self._error("validation", f"No Dockerfile.test at {self.config.test_dockerfile}")
        if not self.config.test_suite_dir.exists():
            return self._error("validation", f"No test_suite/ at {self.config.test_suite_dir}")

        try:
            return self._execute(start_time)
        finally:
            self.docker_ops.cleanup()

    def _execute(self, start_time: float) -> BenchmarkResults:
        # Step 1: Build implementation image
        try:
            logger.info("=== Step 1/5: Building implementation image ===")
            self.docker_ops.build_impl_image()
        except ImplBuildError as exc:
            return self._error("impl_build", str(exc))

        # Step 2: Build test image
        try:
            logger.info("=== Step 2/5: Building test image ===")
            self.docker_ops.build_test_image()
        except TestBuildError as exc:
            return self._error("test_build", str(exc))

        # Step 3: Create network and run impl container
        logger.info("=== Step 3/5: Starting implementation container ===")
        network = self.docker_ops.create_network()
        impl_container = self.docker_ops.run_impl_container(network)

        # Step 4: Wait for impl to be ready
        try:
            logger.info("=== Step 4/5: Waiting for implementation readiness ===")
            self.health.wait_until_ready(impl_container)
        except (ImplStartupError, ImplStartupTimeout) as exc:
            return self._error("impl_startup", str(exc))

        # Step 5: Run tests
        logger.info("=== Step 5/5: Running tests ===")
        test_container = self.docker_ops.run_test_container(network)

        try:
            result = self.docker_ops.wait_for_container(
                test_container, self.config.test_timeout
            )
            exit_code = result.get("StatusCode", -1)
            logger.info(f"Test container exited with code {exit_code}")
        except Exception as exc:
            logger.warning(f"Test execution timeout or error: {exc}")
            # Try to collect partial results anyway
            pass

        # Collect results
        results = collect_results(self.docker_ops, test_container, self.config)
        results.duration_seconds = time.monotonic() - start_time

        # Print summary
        self._print_summary(results)
        return results

    def _error(self, stage: str, message: str) -> BenchmarkResults:
        logger.error(f"[{stage}] {message}")
        return BenchmarkResults(
            total=0,
            errors=1,
            tests=[
                TestResult(
                    name=stage,
                    file="",
                    status="error",
                    duration_seconds=0.0,
                    error_message=message,
                )
            ],
        )

    def _print_summary(self, results: BenchmarkResults):
        total = results.total
        passed = results.passed
        failed = results.failed
        errors = results.errors
        skipped = results.skipped
        duration = results.duration_seconds

        print()
        print("=" * 60)
        print(f"Results: {passed}/{total} passed, {failed} failed, "
              f"{errors} errors, {skipped} skipped")
        print(f"Duration: {duration:.1f}s")
        print("=" * 60)

        failed_tests = [t for t in results.tests if t.status in ("failed", "error")]
        if failed_tests:
            print()
            print("Failed tests:")
            for t in failed_tests[:20]:
                msg = (t.error_message or "").split("\n")[0][:120]
                print(f"  - {t.name}: {msg}")
            if len(failed_tests) > 20:
                print(f"  ... and {len(failed_tests) - 20} more")
