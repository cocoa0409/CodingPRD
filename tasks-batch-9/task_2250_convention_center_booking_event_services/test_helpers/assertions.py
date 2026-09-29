"""Domain assertion helpers.

These wrap the repeated shape and money checks so individual tests read as
statements about the domain rather than as dictionary plumbing.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_identity_and_audit_fields(entity: Dict[str, Any], *, expected_version: Optional[int] = None) -> None:
    """Assert the four properties every mutable row carries."""
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), f"bad created_at: {entity.get('created_at')!r}"
    assert is_iso8601_timestamp(entity.get("updated_at")), f"bad updated_at: {entity.get('updated_at')!r}"
    assert isinstance(entity.get("version"), int), f"version is not an integer: {entity.get('version')!r}"
    assert entity["version"] >= 1, f"version must start at 1, got {entity['version']}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_record(record: Dict[str, Any]) -> None:
    """Assert an immutable record carries only an identifier and a creation stamp."""
    assert is_valid_uuid(record.get("id")), f"id is not a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record.get("created_at")), f"bad created_at: {record.get('created_at')!r}"
    assert "updated_at" not in record, "append-only record must not carry updated_at"
    assert "version" not in record, "append-only record must not carry version"


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert a set of field values in one call, reporting every mismatch."""
    mismatches = []
    for field, value in expected.items():
        assert field in entity, f"missing field {field!r} in {sorted(entity)}"
        if entity[field] != value:
            mismatches.append(f"{field}: expected {value!r}, got {entity[field]!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_field_absent(entity: Dict[str, Any], field: str) -> None:
    assert field not in entity, f"field {field!r} should be absent but was {entity.get(field)!r}"


def assert_money_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money field is exactly the expected whole number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual} cents"


def assert_crew_hours(actual: Any, expected: float, label: str = "crew hours") -> None:
    """Assert a crew-hour quantity matches to one decimal place."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), 1) == round(float(expected), 1), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_settlement_money(
    settlement: Dict[str, Any],
    *,
    line_subtotal_cents: Optional[int] = None,
    facility_service_fee_cents: Optional[int] = None,
    deposit_applied_cents: Optional[int] = None,
    grand_total_cents: Optional[int] = None,
) -> None:
    if line_subtotal_cents is not None:
        assert_money_cents(settlement.get("line_subtotal_cents"), line_subtotal_cents, "line_subtotal_cents")
    if facility_service_fee_cents is not None:
        assert_money_cents(
            settlement.get("facility_service_fee_cents"),
            facility_service_fee_cents,
            "facility_service_fee_cents",
        )
    if deposit_applied_cents is not None:
        assert_money_cents(
            settlement.get("deposit_applied_cents"), deposit_applied_cents, "deposit_applied_cents"
        )
    if grand_total_cents is not None:
        assert_money_cents(settlement.get("grand_total_cents"), grand_total_cents, "grand_total_cents")


def assert_pagination_meta(
    meta: Dict[str, Any],
    *,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    for key in ("total_count", "has_more", "limit", "offset"):
        assert key in meta, f"pagination meta missing {key!r}: {meta}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, f"has_more: expected {has_more}, got {meta['has_more']}"
    if limit is not None:
        assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"


def assert_ids_in_order(items: Iterable[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [item["id"] for item in items]
    assert actual == expected_ids, f"expected order {expected_ids}, got {actual}"


def assert_ascending(items: Iterable[Dict[str, Any]], field: str) -> None:
    values = [item[field] for item in items]
    assert values == sorted(values), f"{field} values are not ascending: {values}"


def assert_version_greater(newer: Dict[str, Any], older: Dict[str, Any]) -> None:
    assert newer["version"] > older["version"], (
        f"version did not advance: {older['version']} -> {newer['version']}"
    )


def find_by_id(items: Iterable[Dict[str, Any]], target_id: str) -> Dict[str, Any]:
    for item in items:
        if item.get("id") == target_id:
            return item
    raise AssertionError(f"identifier {target_id} not present in listing")
