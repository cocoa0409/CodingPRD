"""
Domain assertion helpers.

Thin wrappers over the framework validators that encode contract-level rules:
the common-field set carried by every resource type, the envelope meta shape,
the pagination meta block, timestamp comparison, and small pure re-derivations
(round_half_up, grade assignment) used to build parametrized expectations.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import COMMON_FIELDS, GRADE_LIMITS, GRADE_RANK


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round to the nearest integer with ties away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def assign_grade(
    test_weight_lbs: float, damage_pct: float, foreign_material_pct: float
) -> str:
    """
    Re-derive the assigned grade from the three grade factors: the best grade
    whose every factor limit is satisfied by all three factors at once.
    """
    for grade in ("US_NO_1", "US_NO_2", "US_NO_3"):
        limits = GRADE_LIMITS[grade]
        if (
            test_weight_lbs >= limits["min_test_weight"]
            and damage_pct <= limits["max_damage"]
            and foreign_material_pct <= limits["max_foreign"]
        ):
            return grade
    return "SAMPLE_GRADE"


def grade_rank(grade: str) -> int:
    return GRADE_RANK[grade]


# ---------------------------------------------------------------------------
# Common field / envelope assertions
# ---------------------------------------------------------------------------
def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    Every resource type in this system carries id, created_at, updated_at and
    version. No resource type omits updated_at or version.
    """
    for field in COMMON_FIELDS:
        assert field in row, f"Resource is missing the common field '{field}': {row}"
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert_timestamp_with_millis(row["created_at"], "created_at")
    assert_timestamp_with_millis(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, f"version must start at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_timestamp_with_millis(value: str, label: str = "timestamp") -> None:
    """An ISO-8601 UTC timestamp with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO-8601: {value!r}"
    assert value.endswith("Z"), f"{label} must be UTC and end with Z: {value!r}"
    assert "." in value, f"{label} must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def normalize_instant(value: str) -> str:
    """Strip fractional seconds so two renderings of the same instant compare."""
    assert isinstance(value, str), f"instant must be a string, got {value!r}"
    text = value.rstrip("Z")
    if "." in text:
        text = text.split(".")[0]
    return text + "Z"


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 instants ignoring fractional-second rendering."""
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """meta.api_request_id starts with req_ and the timestamp carries millis."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_timestamp_with_millis(meta["api_request_timestamp"], "api_request_timestamp")


def assert_error_meta_is_minimal(body: Dict[str, Any]) -> None:
    """An error envelope's meta block carries only the two request fields."""
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must carry only the two request fields, got {sorted(body['meta'])}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"Pagination meta is missing '{key}': {meta}"
    if limit is not None:
        assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more {has_more}, got {meta['has_more']}"
        )


def assert_fields_equal(row: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert a batch of field values, reporting every mismatch at once."""
    mismatches = []
    for field, want in expected.items():
        assert field in row, f"Resource is missing field '{field}': {sorted(row)}"
        got = row[field]
        if got != want:
            mismatches.append(f"{field}: expected {want!r}, got {got!r}")
    assert not mismatches, "Field mismatches: " + "; ".join(mismatches)


def assert_has_fields(row: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [f for f in fields if f not in row]
    assert not missing, f"Resource is missing declared fields {missing}: {sorted(row)}"


def assert_ordered_by_created_at(rows: List[Dict[str, Any]]) -> None:
    """List reads are ordered by created_at ascending."""
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"Rows are not ordered by created_at: {stamps}"


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["id"] for r in rows]
