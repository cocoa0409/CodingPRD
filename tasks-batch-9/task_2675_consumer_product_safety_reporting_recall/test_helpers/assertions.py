"""Domain assertions expressed in the vocabulary of the contract."""

from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import DEFAULT_CLOCK
from .types import COMMON_FIELDS


def assert_common_fields(record: Dict[str, Any], expected_version: int = 1) -> None:
    """Every persisted record carries id, created_at, updated_at and version."""
    for field in COMMON_FIELDS:
        assert field in record, f"missing common field {field}: {record}"
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']}"
    assert "_" not in str(record["id"]), f"id carries a type prefix: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int), record["version"]
    assert record["version"] == expected_version, (
        f"expected version {expected_version}, got {record['version']}"
    )


def assert_millisecond_timestamp(value: str) -> None:
    """Timestamps are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), value
    assert is_iso8601_timestamp(value), value
    assert "." in value, f"timestamp lacks fractional digits: {value}"
    fraction = value.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits: {value}"


def assert_fields_null(record: Dict[str, Any], *fields: str) -> None:
    """The named fields are present and null."""
    for field in fields:
        assert field in record, f"missing field {field}: {record}"
        assert record[field] is None, f"expected {field} null, got {record[field]}"


def assert_field_values(record: Dict[str, Any], **expected: Any) -> None:
    """Each named field carries exactly the expected value."""
    for field, value in expected.items():
        assert field in record, f"missing field {field}: {record}"
        assert record[field] == value, (
            f"expected {field} == {value!r}, got {record[field]!r}"
        )


def assert_decimal_equals(actual: Any, expected: str, places: int = 2) -> None:
    """A stored decimal figure equals the expected value at the given scale."""
    quantum = Decimal(1).scaleb(-places)
    actual_dec = Decimal(str(actual)).quantize(quantum)
    expected_dec = Decimal(expected).quantize(quantum)
    assert actual_dec == expected_dec, f"expected {expected_dec}, got {actual_dec}"


def assert_unit_ledger_conserved(recall: Dict[str, Any]) -> None:
    """units_corrected plus units_outstanding always equals units_in_commerce."""
    assert (
        recall["units_corrected"] + recall["units_outstanding"]
        == recall["units_in_commerce"]
    ), (
        f"ledger not conserved: {recall['units_corrected']} + "
        f"{recall['units_outstanding']} != {recall['units_in_commerce']}"
    )


def assert_reserve_conserved(case: Dict[str, Any]) -> None:
    """reserved_cents plus available_cents always equals the frozen assessment."""
    assert (
        case["reserved_cents"] + case["available_cents"]
        == case["assessed_penalty_cents"]
    ), (
        f"reserve not conserved: {case['reserved_cents']} + "
        f"{case['available_cents']} != {case['assessed_penalty_cents']}"
    )


def assert_integer_cents(record: Dict[str, Any], *fields: str) -> None:
    """Every money field is an integer number of cents."""
    for field in fields:
        value = record[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} is not an integer number of cents: {value!r}"
        )


def assert_error_envelope(body: Dict[str, Any], expected_error_id: str) -> None:
    """An error body carries the declared envelope and nothing else."""
    assert body.get("response_type") == "error", body
    meta = body.get("meta", {})
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, meta
    assert str(meta["api_request_id"]).startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta
    data = body.get("data", {})
    assert data.get("error_id") == expected_error_id, data
    assert isinstance(data.get("message"), str) and data["message"], data


def assert_success_envelope(body: Dict[str, Any], response_type: str = "object") -> None:
    """A success body carries the declared envelope."""
    assert body.get("response_type") == response_type, body
    meta = body.get("meta", {})
    assert str(meta.get("api_request_id", "")).startswith("req_"), meta
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), meta


def assert_single_resource_meta(body: Dict[str, Any]) -> None:
    """Single-resource responses omit all four pagination fields."""
    meta = body.get("meta", {})
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single resource leaked {field}: {meta}"


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    """Collection results are always ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


def assert_ids_equal(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """The listed rows are exactly the expected ones, in order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"expected {list(expected_ids)}, got {actual}"


def assert_version_advanced(
    before: Dict[str, Any], after: Dict[str, Any], by: int = 1
) -> None:
    """A mutation advances the row's version by exactly the expected step."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )


def assert_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], *fields: str
) -> None:
    """The named fields did not move between two reads of the same row."""
    for field in fields:
        assert before[field] == after[field], (
            f"{field} moved from {before[field]!r} to {after[field]!r}"
        )


def assert_clock_default(value: str) -> None:
    """Before any client sets it the logical clock reads the declared default."""
    assert str(value).startswith(DEFAULT_CLOCK[:19]), (
        f"expected the declared default clock, got {value}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """List meta carries limit and offset as applied plus the row totals."""
    if limit is not None:
        assert meta["limit"] == limit, meta
    if offset is not None:
        assert meta["offset"] == offset, meta
    if total_count is not None:
        assert meta["total_count"] == total_count, meta
    if has_more is not None:
        assert meta["has_more"] is has_more, meta
