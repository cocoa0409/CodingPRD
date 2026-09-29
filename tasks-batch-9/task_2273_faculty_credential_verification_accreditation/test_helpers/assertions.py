"""Domain assertion helpers shared by the suite."""

from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)


def assert_common_entity_fields(entity: Dict[str, Any], expected_version: int = None):
    """PRD 2.5: every entity carries id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"entity is missing the common field {field!r}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at is not ISO 8601: {entity['created_at']!r}"
    assert is_iso8601_timestamp(
        entity["updated_at"]
    ), f"updated_at is not ISO 8601: {entity['updated_at']!r}"
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_score(actual: Any, expected: float, label: str = "score"):
    """PRD 2.6: scores and ratios carry four decimal places."""
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"{label} should be {expected:.4f}, got {actual!r}"
    )


def assert_risk_value(actual: Any, expected: float, label: str = "risk index"):
    """PRD 2.6: risk indices carry two decimal places."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"{label} should be {expected:.2f}, got {actual!r}"
    )


def assert_hours(actual: Any, expected: float, label: str = "contact hours"):
    """PRD 2.6: professional-development contact hours carry one decimal place."""
    assert actual == pytest.approx(expected, abs=0.05), (
        f"{label} should be {expected:.1f}, got {actual!r}"
    )


def assert_cents(actual: Any, expected: int, label: str = "amount"):
    """PRD 2.6: money is an integer count of cents."""
    assert isinstance(actual, int), f"{label} must be an integer cent count, got {actual!r}"
    assert actual == expected, f"{label} should be {expected} cents, got {actual}"


def _instant(text: str):
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    from datetime import datetime, timezone

    cleaned = text.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    return datetime.fromisoformat(cleaned).astimezone(timezone.utc)


def assert_clock_instant(actual: Any, expected: str, label: str = "timestamp"):
    """Assert a clock-stamped field carries the logical clock instant.

    PRD 2.5 pins the three-fractional-digit rendering for ``created_at`` and
    ``updated_at`` only, so fields the PRD merely describes as "stamped from the
    logical clock" are compared as instants rather than as literal text.
    """
    assert isinstance(actual, str), f"{label} must be stamped, got {actual!r}"
    assert _instant(actual) == _instant(expected), (
        f"{label} should carry the logical clock instant {expected}, got {actual!r}"
    )


def assert_fields(entity: Dict[str, Any], **expected):
    """Assert a batch of scalar fields with a readable message per mismatch."""
    mismatches = []
    for field, want in expected.items():
        got = entity.get(field, "<missing>")
        if got != want:
            mismatches.append(f"{field}: expected {want!r}, got {got!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_ordered_codes(
    actual: Optional[Sequence[str]], expected: Sequence[str], label: str = "codes"
):
    """Assert a derived code list matches exactly, order included."""
    assert list(actual or []) == list(expected), (
        f"{label} should be {list(expected)!r} in that declared order, got {actual!r}"
    )


def assert_assignment_verdict(
    assignment: Dict[str, Any],
    status: str,
    qualification_basis: Optional[str],
    exception_code: Optional[str] = None,
    alignment_score: Optional[float] = None,
):
    """Assert the four derived qualification fields of PRD 3.4 together."""
    assert_fields(
        assignment,
        status=status,
        qualification_basis=qualification_basis,
        exception_code=exception_code,
    )
    if alignment_score is not None:
        assert_score(assignment.get("alignment_score"), alignment_score, "alignment_score")


def assert_roster_snapshot(roster: Dict[str, Any], **expected):
    """Assert roster snapshot counters, tolerating the float ratio field."""
    ratio = expected.pop("adequacy_ratio_snapshot", None)
    blocking = expected.pop("blocking_reason_codes", None)
    assert_fields(roster, **expected)
    if ratio is not None:
        assert_score(
            roster.get("adequacy_ratio_snapshot"), ratio, "adequacy_ratio_snapshot"
        )
    if blocking is not None:
        assert_ordered_codes(
            roster.get("blocking_reason_codes"), blocking, "blocking_reason_codes"
        )


def assert_program_adequacy(program: Dict[str, Any], **expected):
    ratio = expected.pop("adequacy_ratio", None)
    assert_fields(program, **expected)
    if ratio is not None:
        assert_score(program.get("adequacy_ratio"), ratio, "adequacy_ratio")


def assert_version_advanced_by(
    entity: Dict[str, Any], baseline_version: int, steps: int = 1
):
    """PRD 2.5/2.7: an accepted write advances its own version by exactly one."""
    assert entity["version"] == baseline_version + steps, (
        f"version should have advanced from {baseline_version} by {steps}, "
        f"got {entity['version']}"
    )


def assert_total_count(meta: Dict[str, Any], expected: int, label: str = "listing"):
    assert meta["total_count"] == expected, (
        f"{label} total_count should be {expected}, got {meta['total_count']}"
    )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def read_version(response) -> int:
    return validate_success(response)["version"]
