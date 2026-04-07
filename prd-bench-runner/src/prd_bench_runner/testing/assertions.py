"""
Generic assertion helpers for API compliance tests.

Validate structural properties (UUID format, timestamp format, decimal precision,
version monotonicity, race outcomes) that every API conformance test suite needs.

Domain-specific assertions (e.g., assert_order, assert_booking) are written
separately and typically call these generic helpers internally.
"""

import concurrent.futures
import re
from typing import Any

import pytest

# ─── Format Validators ────────────────────────────────

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$"
)


def is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID v4 format."""
    return bool(_UUID_RE.match(value)) if isinstance(value, str) else False


def is_iso8601_timestamp(value: str) -> bool:
    """Check if a string is a valid ISO 8601 UTC timestamp with optional milliseconds."""
    return bool(_ISO8601_RE.match(value)) if isinstance(value, str) else False


# ─── Value Assertions ─────────────────────────────────

def assert_cost_precision(cost: float, decimal_places: int = 2) -> None:
    """Assert monetary value has at most N decimal places."""
    rounded = round(cost, decimal_places)
    assert rounded == pytest.approx(cost), (
        f"Cost {cost} has more than {decimal_places} decimal places"
    )


def assert_version_incremented(
    new_version: int, old_version: int, min_increment: int = 1
) -> None:
    """Assert OCC version monotonically increased."""
    assert new_version >= old_version + min_increment, (
        f"Version did not increment: {old_version} → {new_version} "
        f"(expected at least +{min_increment})"
    )


def assert_timestamp_format(timestamp: str) -> None:
    """Assert string is a valid ISO 8601 UTC timestamp."""
    assert is_iso8601_timestamp(timestamp), (
        f"Not a valid ISO 8601 timestamp: {timestamp!r}"
    )


# ─── Race Condition Assertions ────────────────────────

def assert_race_outcome(
    results: list, expected_successes: int, expected_failures: int
) -> dict:
    """
    Validate the outcome of a concurrent race between multiple operations.
    Returns {"successes": [...], "failures": [...]}.
    """
    successes = [r for r in results if 200 <= r.status_code < 300]
    failures = [r for r in results if r.status_code >= 400]
    assert len(successes) == expected_successes, (
        f"Expected {expected_successes} successes, got {len(successes)} "
        f"(statuses: {[r.status_code for r in results]})"
    )
    assert len(failures) == expected_failures, (
        f"Expected {expected_failures} failures, got {len(failures)} "
        f"(statuses: {[r.status_code for r in results]})"
    )
    return {"successes": successes, "failures": failures}


def assert_exactly_one_succeeds(result_a: Any, result_b: Any) -> dict:
    """Binary race: exactly one succeeds, one fails."""
    return assert_race_outcome([result_a, result_b], 1, 1)


def assert_at_least_one_succeeds(*results: Any) -> dict:
    """At least one operation must succeed."""
    successes = [r for r in results if 200 <= r.status_code < 300]
    failures = [r for r in results if r.status_code >= 400]
    assert len(successes) >= 1, (
        f"Expected at least 1 success, got 0 "
        f"(statuses: {[r.status_code for r in results]})"
    )
    return {"successes": successes, "failures": failures}


def run_race(*operations) -> list:
    """
    Execute operations concurrently and return all results.
    Each operation is a zero-arg callable returning requests.Response.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(operations)) as ex:
        futures = [ex.submit(op) for op in operations]
        return [f.result() for f in concurrent.futures.as_completed(futures)]
