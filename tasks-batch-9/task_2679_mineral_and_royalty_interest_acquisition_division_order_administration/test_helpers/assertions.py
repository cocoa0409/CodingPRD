"""Domain assertions: envelope shape, precision, and conserved quantities."""

from decimal import Decimal
from typing import Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ACREAGE_DP,
    DECIMAL_INTEREST_DP,
    MONEY_DP,
    RATE_DP,
)
from .types import COMMON_FIELDS_APPEND_ONLY, COMMON_FIELDS_FULL


def as_decimal(value) -> Decimal:
    """Coerce a JSON numeric field to Decimal without binary-float drift."""
    assert value is not None, "expected a numeric value, got null"
    return Decimal(str(value))


def assert_quantized(value, places: int, label: str = "value") -> Decimal:
    """The value carries no more than `places` decimal places."""
    dec = as_decimal(value)
    exponent = -dec.as_tuple().exponent
    assert exponent <= places, (
        f"{label} {value} carries {exponent} decimal places, "
        f"more than the {places} the contract allows"
    )
    return dec


def assert_money(actual, expected, label: str = "money") -> None:
    """Money equality at 2 decimal places."""
    got = as_decimal(actual).quantize(Decimal("0.01"))
    want = as_decimal(expected).quantize(Decimal("0.01"))
    assert got == want, f"{label}: expected {want}, got {got}"


def assert_acreage(actual, expected, label: str = "acreage") -> None:
    """Acreage equality at 4 decimal places."""
    got = as_decimal(actual).quantize(Decimal("0.0001"))
    want = as_decimal(expected).quantize(Decimal("0.0001"))
    assert got == want, f"{label}: expected {want}, got {got}"


def assert_rate(actual, expected, label: str = "rate") -> None:
    """Rate or fraction equality at 6 decimal places."""
    got = as_decimal(actual).quantize(Decimal("0.000001"))
    want = as_decimal(expected).quantize(Decimal("0.000001"))
    assert got == want, f"{label}: expected {want}, got {got}"


def assert_burden(actual, expected, label: str = "burden fraction") -> None:
    """Burden fraction equality at 4 decimal places."""
    got = as_decimal(actual).quantize(Decimal("0.0001"))
    want = as_decimal(expected).quantize(Decimal("0.0001"))
    assert got == want, f"{label}: expected {want}, got {got}"


def assert_decimal_interest(actual, expected, label: str = "decimal interest") -> None:
    """Decimal interest equality at 8 decimal places."""
    got = as_decimal(actual).quantize(Decimal("0.00000001"))
    want = as_decimal(expected).quantize(Decimal("0.00000001"))
    assert got == want, f"{label}: expected {want}, got {got}"


def assert_envelope_meta(body: dict) -> None:
    """meta carries a req_-prefixed request id and a millisecond ISO timestamp."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp is not ISO8601: {meta['api_request_timestamp']}"
    )


def assert_identity_fields(entity: dict, versioned: bool = True) -> None:
    """id is a bare UUID, created_at is an ISO8601 timestamp, version starts at 1."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO8601: {entity['created_at']}"
    )
    if versioned:
        assert is_iso8601_timestamp(entity["updated_at"]), (
            f"updated_at is not ISO8601: {entity['updated_at']}"
        )
        assert isinstance(entity["version"], int) and entity["version"] >= 1, (
            f"version must be a positive integer, got {entity.get('version')!r}"
        )
    else:
        assert "version" not in entity, "append-only entity must not carry a version"
        assert "updated_at" not in entity, (
            "append-only entity must not carry an updated_at"
        )


def assert_has_fields(entity: dict, field_names: Sequence[str]) -> None:
    missing = [name for name in field_names if name not in entity]
    assert not missing, f"response is missing declared fields: {missing}"


def assert_full_entity_shape(entity: dict, field_names: Sequence[str]) -> None:
    """Entity carries its declared fields plus id/created_at/updated_at/version."""
    assert_has_fields(entity, list(field_names) + COMMON_FIELDS_FULL)
    assert_identity_fields(entity, versioned=True)


def assert_append_only_entity_shape(entity: dict, field_names: Sequence[str]) -> None:
    """Entity carries its declared fields plus only id and created_at."""
    assert_has_fields(entity, list(field_names) + COMMON_FIELDS_APPEND_ONLY)
    assert_identity_fields(entity, versioned=False)


def assert_version_bumped_by(before: dict, after: dict, delta: int = 1) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version'] + delta}, got {after['version']}"
    )


def assert_ordered_by(items: List[dict], key: str, descending: bool = False) -> None:
    values = [item[key] for item in items]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"items are not ordered by {key} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )


def assert_ordered_by_pair(
    items: List[dict], primary: str, secondary: str, descending: bool = False
) -> None:
    values = [(item[primary], item[secondary]) for item in items]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"items are not ordered by ({primary}, {secondary}): {values}"
    )


def assert_unit_acreage_conserved(unit: dict, allocations: Iterable[dict]) -> None:
    """Sum of ACTIVE/PUGH_RELEASED allocated acres plus unallocated_acres equals
    unit_gross_acres, at 4 decimal places."""
    counted = [
        allocation
        for allocation in allocations
        if allocation["allocation_status"] in ("ACTIVE", "PUGH_RELEASED")
    ]
    total = sum(
        (as_decimal(allocation["allocated_acres"]) for allocation in counted),
        Decimal("0"),
    ) + as_decimal(unit["unallocated_acres"])
    assert_acreage(
        total, unit["unit_gross_acres"], "conserved unit acreage total"
    )


def assert_division_order_revenue_conserved(
    order: dict, details: Iterable[dict], suspense_accounts: Iterable[dict]
) -> None:
    """Sum of every detail's net_amount equals paid_net_total plus the sum of
    suspense accrued_amount, at 2 decimal places."""
    left = sum((as_decimal(detail["net_amount"]) for detail in details), Decimal("0"))
    right = as_decimal(order["paid_net_total"]) + sum(
        (as_decimal(account["accrued_amount"]) for account in suspense_accounts),
        Decimal("0"),
    )
    assert_money(left, right, "conserved division-order net revenue")


def assert_pagination_meta(
    meta: dict,
    limit: int,
    offset: int,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """meta carries limit, offset, total_count and has_more."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination meta is missing {field}"
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
