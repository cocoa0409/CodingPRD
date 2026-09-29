"""Domain assertions.

Helpers here encode invariants that recur across the suite: the shape of the
response envelope, the presence of the common resource fields, seat conservation,
ledger sign conventions and the fee fingerprint format.  Each raises an
``AssertionError`` with a message naming the business rule it protects.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BP_ONE, TAX_RATE_BP
from .types import COMMON_FIELD_NAMES, IMMUTABLE_COMMON_FIELD_NAMES


# ---------------------------------------------------------------------------
# Envelope and common fields
# ---------------------------------------------------------------------------
def assert_envelope(body: Dict[str, Any]) -> None:
    """Every response carries meta.api_request_id, response_type and data."""
    assert "meta" in body, f"response has no meta block: {body}"
    assert "data" in body, f"response has no data block: {body}"
    meta = body["meta"]
    assert "api_request_id" in meta, f"meta has no api_request_id: {meta}"
    assert str(meta["api_request_id"]).startswith(
        "req_"
    ), f"api_request_id must start with 'req_': {meta['api_request_id']}"
    assert "api_request_timestamp" in meta, f"meta has no api_request_timestamp: {meta}"
    assert body.get("response_type") in (
        "object",
        "array",
        "error",
    ), f"response_type must be object, array or error: {body.get('response_type')!r}"


def assert_pagination_meta(meta: Dict[str, Any], limit=None, offset=None, total_count=None, has_more=None) -> None:
    """A list response carries limit, offset, total_count and has_more in meta."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"list response meta is missing {field}: {meta}"
    if limit is not None:
        assert meta["limit"] == limit, f"limit should be {limit} but is {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset should be {offset} but is {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count should be {total_count} but is {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more should be {has_more} but is {meta['has_more']}"
        )


def assert_common_fields(resource: Dict[str, Any]) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    for field in COMMON_FIELD_NAMES:
        assert field in resource, f"resource is missing common field {field}: {resource}"
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at is not ISO-8601: {resource['created_at']}"
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"updated_at is not ISO-8601: {resource['updated_at']}"
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, f"version starts at 1: {resource['version']}"


def assert_immutable_common_fields(entry: Dict[str, Any]) -> None:
    """A ledger entry carries only id and created_at: it is never updated."""
    for field in IMMUTABLE_COMMON_FIELD_NAMES:
        assert field in entry, f"ledger entry is missing {field}: {entry}"
    assert is_valid_uuid(entry["id"]), f"id is not a UUID: {entry['id']}"
    assert is_iso8601_timestamp(
        entry["created_at"]
    ), f"created_at is not ISO-8601: {entry['created_at']}"
    assert (
        "updated_at" not in entry
    ), "an append-only ledger entry must not expose updated_at"
    assert "version" not in entry, "an append-only ledger entry must not expose version"


def assert_has_fields(resource: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [f for f in fields if f not in resource]
    assert not missing, f"resource is missing declared fields {missing}: {resource}"


def assert_field_values(resource: Dict[str, Any], **expected) -> None:
    for field, value in expected.items():
        assert field in resource, f"resource is missing field {field}: {resource}"
        assert resource[field] == value, (
            f"{field} should be {value!r} but is {resource[field]!r}"
        )


# ---------------------------------------------------------------------------
# Logical-clock instants
# ---------------------------------------------------------------------------
def as_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC string into the instant it denotes.

    The contract pins the *instant* a clock-derived field carries - "a
    ``valid_from`` equal to the logical clock, and a ``valid_until`` exactly one
    hour later" - while the only rendering convention it states anywhere is "an
    ISO 8601 UTC instant with three fractional digits".  A trailing ``.000`` and
    a bare ``Z`` therefore denote the same instant, so clock-derived fields are
    compared as instants rather than byte for byte.
    """
    assert isinstance(value, str), f"expected an ISO 8601 timestamp string: {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_instant(resource: Dict[str, Any], field: str, expected_iso: str) -> None:
    """A clock-derived field must denote the expected UTC instant."""
    assert field in resource, f"resource is missing field {field}: {resource}"
    actual = resource[field]
    assert as_instant(actual) == as_instant(expected_iso), (
        f"{field} should be the instant {expected_iso} but is {actual!r}"
    )


def assert_instants(resource: Dict[str, Any], **expected) -> None:
    """Assert several clock-derived fields at once."""
    for field, expected_iso in expected.items():
        assert_instant(resource, field, expected_iso)


# ---------------------------------------------------------------------------
# Money and basis points
# ---------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round a rational amount to a whole cent, halves going away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bp(amount_cents: int, factor_bp: int) -> int:
    """Multiply a cent amount by a basis-point factor, rounding half up."""
    return round_half_up(Decimal(amount_cents) * Decimal(factor_bp) / Decimal(BP_ONE))


def tax_for(gross_cents: int, tax_treatment: str) -> int:
    """The tax a gross amount attracts under a tax treatment."""
    return apply_bp(gross_cents, TAX_RATE_BP[tax_treatment])


def assert_money_field(resource: Dict[str, Any], field: str, expected_cents: int) -> None:
    actual = resource.get(field)
    assert isinstance(actual, int), f"{field} must be an integer number of cents: {actual!r}"
    assert actual == expected_cents, (
        f"{field} should be {expected_cents} cents but is {actual} cents"
    )


# ---------------------------------------------------------------------------
# Fee fingerprint
# ---------------------------------------------------------------------------
def build_fee_fingerprint(code: str, revision_no: int, items: List[tuple]) -> str:
    """Compose the canonical fingerprint string.

    ``items`` is a list of ``(sku, inclusion, quantity, effective_unit_cents)``
    tuples; the components are sorted by sku ascending, exactly as the contract
    requires, so a caller may pass them in any order.
    """
    parts = [
        f"{sku}:{inclusion}:{quantity}:{effective_unit}"
        for sku, inclusion, quantity, effective_unit in sorted(items, key=lambda i: i[0])
    ]
    return f"{code}|{revision_no}|" + ";".join(parts)


def assert_fingerprint(resource: Dict[str, Any], field: str, expected: str) -> None:
    actual = resource.get(field)
    assert actual == expected, f"{field} should be {expected!r} but is {actual!r}"


# ---------------------------------------------------------------------------
# Seat inventory
# ---------------------------------------------------------------------------
def assert_seat_conservation(segment: Dict[str, Any]) -> None:
    """available_seats == total_seats - held_seats - sold_seats, always."""
    total = segment["total_seats"]
    held = segment["held_seats"]
    sold = segment["sold_seats"]
    available = segment["available_seats"]
    assert available == total - held - sold, (
        "seat conservation broken: "
        f"total {total} - held {held} - sold {sold} != available {available}"
    )


def assert_segment_counts(
    segment: Dict[str, Any],
    total_seats: Optional[int] = None,
    held_seats: Optional[int] = None,
    sold_seats: Optional[int] = None,
    available_seats: Optional[int] = None,
) -> None:
    if total_seats is not None:
        assert segment["total_seats"] == total_seats, (
            f"total_seats should be {total_seats} but is {segment['total_seats']}"
        )
    if held_seats is not None:
        assert segment["held_seats"] == held_seats, (
            f"held_seats should be {held_seats} but is {segment['held_seats']}"
        )
    if sold_seats is not None:
        assert segment["sold_seats"] == sold_seats, (
            f"sold_seats should be {sold_seats} but is {segment['sold_seats']}"
        )
    if available_seats is not None:
        assert segment["available_seats"] == available_seats, (
            f"available_seats should be {available_seats} but is {segment['available_seats']}"
        )
    assert_seat_conservation(segment)


# ---------------------------------------------------------------------------
# Revenue ledger
# ---------------------------------------------------------------------------
def find_entries(
    entries: List[Dict[str, Any]],
    entry_type: Optional[str] = None,
    category: Optional[str] = None,
    product_sku: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter ledger rows by entry type, category and/or product sku."""
    result = entries
    if entry_type is not None:
        result = [e for e in result if e["entry_type"] == entry_type]
    if category is not None:
        result = [e for e in result if e["category"] == category]
    if product_sku is not None:
        result = [e for e in result if e["product_sku"] == product_sku]
    return result


def find_one_entry(entries: List[Dict[str, Any]], **filters) -> Dict[str, Any]:
    """Exactly one ledger row must match, otherwise the ledger is wrong."""
    matches = find_entries(entries, **filters)
    assert len(matches) == 1, (
        f"expected exactly one ledger row matching {filters}, found {len(matches)}: {matches}"
    )
    return matches[0]


def assert_entry_amounts(
    entry: Dict[str, Any], gross_cents: int, tax_cents: int, net_cents: int
) -> None:
    assert entry["gross_cents"] == gross_cents, (
        f"gross_cents should be {gross_cents} but is {entry['gross_cents']}"
    )
    assert entry["tax_cents"] == tax_cents, (
        f"tax_cents should be {tax_cents} but is {entry['tax_cents']}"
    )
    assert entry["net_cents"] == net_cents, (
        f"net_cents should be {net_cents} but is {entry['net_cents']}"
    )
    assert entry["net_cents"] == entry["gross_cents"] - entry["tax_cents"], (
        "net_cents must equal gross_cents minus tax_cents: "
        f"{entry['net_cents']} != {entry['gross_cents']} - {entry['tax_cents']}"
    )


def assert_recognized_net_matches_ledger(
    booking: Dict[str, Any], entries: List[Dict[str, Any]]
) -> None:
    """recognized_ancillary_net_cents is the signed non-transport net total."""
    expected = sum(e["net_cents"] for e in entries if e["category"] != "AIR_TRANSPORT")
    assert booking["recognized_ancillary_net_cents"] == expected, (
        "recognized_ancillary_net_cents should equal the signed sum of non-transport "
        f"ledger net amounts {expected} but is {booking['recognized_ancillary_net_cents']}"
    )


def assert_allocation_conserves_fare(
    entries: List[Dict[str, Any]], fare_component_cents: int
) -> None:
    """The allocation rows must sum back to the fare component exactly."""
    allocations = find_entries(entries, entry_type="ALLOCATION")
    total = sum(e["gross_cents"] for e in allocations)
    assert total == fare_component_cents, (
        "allocation gross amounts must sum to the fare component "
        f"{fare_component_cents} but sum to {total}"
    )
