"""Domain assertions shared by the suite."""

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMMON_FIELDS,
    ECONOMICS_VIEW_FIELDS,
    SATISFACTION_ABSENT_FIELDS,
    SATISFACTION_AUDIT_FIELDS,
)

JsonDict = Dict[str, Any]


def assert_audit_fields(row: Mapping[str, Any], expected_version: Optional[int] = None):
    """Every family but SatisfactionAssessment carries the full audit set."""
    for field in COMMON_FIELDS:
        assert field in row, f"missing audit field {field!r} on {sorted(row)}"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int), row["version"]
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_freshly_created(row: Mapping[str, Any]) -> None:
    """A newly written row starts at version 1 (PRD 2.4)."""
    assert_audit_fields(row, expected_version=1)


def assert_no_mutable_audit_fields(row: Mapping[str, Any]) -> None:
    """A satisfaction assessment carries only ``id`` and ``created_at``."""
    for field in SATISFACTION_AUDIT_FIELDS:
        assert field in row, f"missing {field!r} on satisfaction assessment"
    assert is_valid_uuid(row["id"]), row["id"]
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    for field in SATISFACTION_ABSENT_FIELDS:
        assert field not in row, (
            f"{field!r} must be absent from a satisfaction assessment payload"
        )


def assert_version_advanced_by(
    before: Mapping[str, Any], after: Mapping[str, Any], delta: int
) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']} + {delta}, got {after['version']}"
    )


def assert_money(row: Mapping[str, Any], field: str, expected: Optional[int]) -> None:
    """Money is always an integer number of cents (PRD 2.8)."""
    actual = row.get(field)
    if expected is None:
        assert actual is None, f"{field}: expected null, got {actual!r}"
        return
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_two_dp(row: Mapping[str, Any], field: str, expected: float) -> None:
    """Percentages, scores and hour aggregates carry two decimal places."""
    actual = row.get(field)
    assert actual is not None, f"{field} is missing or null"
    assert abs(float(actual) - expected) < 1e-9, (
        f"{field}: expected {expected}, got {actual}"
    )
    assert round(float(actual), 2) == float(actual), (
        f"{field}: {actual} carries more than two decimal places"
    )


def assert_fields(row: Mapping[str, Any], **expected: Any) -> None:
    for field, value in expected.items():
        assert field in row, f"missing field {field!r} on {sorted(row)}"
        assert row[field] == value, (
            f"{field}: expected {value!r}, got {row[field]!r}"
        )


def assert_economics_view(view: Mapping[str, Any], **expected: Any) -> None:
    """The computed read exposes exactly the six declared keys (PRD 3.7)."""
    assert set(view) == set(ECONOMICS_VIEW_FIELDS), (
        f"economics view keys were {sorted(view)}, "
        f"expected exactly {sorted(ECONOMICS_VIEW_FIELDS)}"
    )
    for field, value in expected.items():
        if isinstance(value, float):
            assert_two_dp(view, field, value)
        else:
            assert view[field] == value, (
                f"{field}: expected {value!r}, got {view[field]!r}"
            )


def assert_ids_equal(rows: Sequence[Mapping[str, Any]], expected_ids: Iterable[str]):
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"row ids were {[row['id'] for row in rows]}, expected {list(expected_ids)}"
    )


def assert_contains_id(rows: Sequence[Mapping[str, Any]], row_id: str) -> None:
    assert any(row["id"] == row_id for row in rows), f"{row_id} absent from listing"


def assert_excludes_id(rows: Sequence[Mapping[str, Any]], row_id: str) -> None:
    assert all(row["id"] != row_id for row in rows), f"{row_id} present in listing"


def assert_pagination_meta(
    meta: Mapping[str, Any], total_count: int, has_more: bool
) -> None:
    assert meta["total_count"] == total_count, (
        f"total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more: expected {has_more}, got {meta['has_more']!r}"
    )
