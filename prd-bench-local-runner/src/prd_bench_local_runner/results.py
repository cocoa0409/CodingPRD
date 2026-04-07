"""Benchmark result types and JUnit XML parser."""

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class TestResult:
    name: str
    file: str
    status: str  # "passed", "failed", "error", "skipped"
    duration_seconds: float
    error_message: Optional[str] = None


@dataclass
class BenchmarkResults:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    tests: list[TestResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: str) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def from_junit_xml(cls, xml_path: str) -> "BenchmarkResults":
        """Parse pytest's --junitxml output into BenchmarkResults."""
        tree = ET.parse(xml_path)
        root = tree.getroot()

        results = cls()
        suite_time = root.get("time")
        if suite_time:
            results.duration_seconds = float(suite_time)

        # Handle both <testsuite> as root and <testsuites><testsuite> nesting
        testsuites = root.findall(".//testsuite") if root.tag == "testsuites" else [root]

        for suite in testsuites:
            for testcase in suite.findall("testcase"):
                name = testcase.get("name", "unknown")
                classname = testcase.get("classname", "")
                time_val = float(testcase.get("time", "0"))

                # Extract file path from classname (pytest format: "test_suite.test_01_crud")
                file_part = classname.replace(".", "/") + ".py" if classname else ""

                failure = testcase.find("failure")
                error = testcase.find("error")
                skipped = testcase.find("skipped")

                if failure is not None:
                    status = "failed"
                    msg = failure.get("message", failure.text or "")
                elif error is not None:
                    status = "error"
                    msg = error.get("message", error.text or "")
                elif skipped is not None:
                    status = "skipped"
                    msg = skipped.get("message", "")
                else:
                    status = "passed"
                    msg = None

                results.tests.append(TestResult(
                    name=name,
                    file=file_part,
                    status=status,
                    duration_seconds=time_val,
                    error_message=msg if msg else None,
                ))

        results.total = len(results.tests)
        results.passed = sum(1 for t in results.tests if t.status == "passed")
        results.failed = sum(1 for t in results.tests if t.status == "failed")
        results.errors = sum(1 for t in results.tests if t.status == "error")
        results.skipped = sum(1 for t in results.tests if t.status == "skipped")

        return results
