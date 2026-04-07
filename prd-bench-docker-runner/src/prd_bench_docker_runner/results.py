"""Collect and parse test results from the test container."""

import tempfile
from pathlib import Path

from loguru import logger
from prd_bench_local_runner.results import BenchmarkResults, TestResult

from .config import RunConfig
from .docker_ops import DockerOperations

RESULTS_XML_PATH = "/app/output/results.xml"


def collect_results(
    docker_ops: DockerOperations,
    container,
    config: RunConfig,
) -> BenchmarkResults:
    """Extract results.xml from the test container and parse it.

    Falls back to an error result if extraction or parsing fails.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        xml_path = Path(tmpdir) / "results.xml"

        if docker_ops.copy_from_container(container, RESULTS_XML_PATH, xml_path):
            logger.info("Collected results.xml from test container")
            try:
                results = BenchmarkResults.from_junit_xml(str(xml_path))
            except Exception as exc:
                logger.warning(f"Failed to parse results.xml: {exc}")
                results = _error_result(
                    "result_parse",
                    f"Failed to parse results.xml: {exc}",
                )
        else:
            logger.warning("No results.xml found in test container")
            logs = docker_ops.get_container_logs(container)
            results = _error_result(
                "no_results",
                f"Test container produced no results.xml.\nLogs:\n{logs[-3000:]}",
            )

    if config.results_file:
        results.save(str(config.results_file))
        logger.info(f"Results saved to {config.results_file}")

    return results


def _error_result(name: str, message: str) -> BenchmarkResults:
    return BenchmarkResults(
        total=0,
        errors=1,
        tests=[
            TestResult(
                name=name,
                file="",
                status="error",
                duration_seconds=0.0,
                error_message=message,
            )
        ],
    )
