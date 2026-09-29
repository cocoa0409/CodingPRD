"""Domain assertions for the Winery DTC API.

These wrap the framework assertions with the specific disciplines this contract
states: liters carried to three decimal places (PRD §2.7), money carried as whole
integer cents that are never strings (PRD §2.7), the four system-managed
properties of PRD §2.5, and the two independent order status dimensions of
PRD §2.11.
"""

import re

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_SALES_TAX_CENTS,
    CANONICAL_ORDER_SHIPPING_CENTS,
    CANONICAL_ORDER_SUBTOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
)

LITERS_TOLERANCE = 0.0005
TRACKING_NUMBER_RE = re.compile(r"^TRK-[0-9a-fA-F]{8}$")


# ---------------------------------------------------------------------------
# Timestamps and instants
# ---------------------------------------------------------------------------
def canonical_instant(value):
    """Normalise an ISO-8601 UTC instant so widths of the fractional part match.

    The contract mints ``2026-08-01T00:00:00.000Z`` (three fractional digits, per
    PRD §2.5) while narrative prose writes the same instant as
    ``2026-08-01T00:00:00Z``.  Comparing the two literally would fail on
    formatting rather than on meaning, so both sides are normalised to exactly
    three fractional digits before comparison.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual, expected):
    """Assert two ISO-8601 UTC instants denote the same moment."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected instant {expected!r}, got {actual!r}"
    )


def assert_system_timestamp(value):
    """An ISO 8601 UTC timestamp with three fractional digits (PRD §2.5)."""
    assert isinstance(value, str), f"Expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"Not an ISO-8601 timestamp: {value!r}"
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value
    ), f"Timestamp must carry exactly three fractional digits: {value!r}"


# ---------------------------------------------------------------------------
# Envelope and identity
# ---------------------------------------------------------------------------
def assert_request_id(meta):
    """``api_request_id`` is server generated and starts with ``req_`` (PRD §2.2)."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with 'req_', got {request_id!r}"
    )


def assert_versioned_identity(row, expected_version=None):
    """The full set of four system-managed properties (PRD §2.5)."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID without prefix: {row['id']!r}"
    assert_system_timestamp(row["created_at"])
    assert_system_timestamp(row["updated_at"])
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_immutable_identity(row):
    """An immutable row carries only ``id`` and ``created_at`` (PRD §2.5)."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID without prefix: {row['id']!r}"
    assert_system_timestamp(row["created_at"])
    assert "updated_at" not in row, "updated_at must be absent from an immutable row"
    assert "version" not in row, "version must be absent from an immutable row"


# ---------------------------------------------------------------------------
# Money and liters
# ---------------------------------------------------------------------------
def assert_cents(value, expected=None, field="amount"):
    """Money is whole integer cents and never a string (PRD §2.7)."""
    assert not isinstance(value, str), f"{field} must not be a string: {value!r}"
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"Expected {field} == {expected}, got {value}"


def assert_liters(value, expected, field="liters"):
    """Volume carried to exactly three decimal places (PRD §2.7)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert value == pytest.approx(expected, abs=LITERS_TOLERANCE), (
        f"Expected {field} == {expected:.3f}, got {value}"
    )


def assert_money_fields_are_integers(row, field_names):
    for name in field_names:
        if name in row and row[name] is not None:
            assert_cents(row[name], field=name)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
ORDER_MONEY_FIELDS = [
    "subtotal_cents",
    "shipping_gross_cents",
    "shipping_tiered_cents",
    "shipping_discount_cents",
    "shipping_cents",
    "excise_tax_cents",
    "sales_tax_cents",
    "pre_fee_total_cents",
    "compliance_handling_fee_cents",
    "total_cents",
    "excise_reversed_cents",
    "sales_tax_reversed_cents",
]


def assert_order_dimensions(order, compliance_status=None, fulfillment_status=None):
    """The two independent status dimensions of PRD §2.11."""
    if compliance_status is not None:
        assert order["compliance_status"] == compliance_status, (
            f"Expected compliance_status {compliance_status}, "
            f"got {order['compliance_status']}"
        )
    if fulfillment_status is not None:
        assert order["fulfillment_status"] == fulfillment_status, (
            f"Expected fulfillment_status {fulfillment_status}, "
            f"got {order['fulfillment_status']}"
        )


def assert_rejection(order, expected_error_id):
    """A screening outcome is recorded in ``rejection_error_id`` (PRD §2.9)."""
    assert order["rejection_error_id"] == expected_error_id, (
        f"Expected rejection_error_id {expected_error_id}, "
        f"got {order['rejection_error_id']}"
    )


def assert_charge_chain(
    order,
    total_liters=None,
    subtotal_cents=None,
    shipping_gross_cents=None,
    shipping_tiered_cents=None,
    shipping_discount_cents=None,
    shipping_cents=None,
    excise_tax_cents=None,
    sales_tax_cents=None,
    pre_fee_total_cents=None,
    compliance_handling_fee_cents=None,
    total_cents=None,
):
    """Assert the frozen figures of the twelve-step chain (PRD §3.5)."""
    assert_money_fields_are_integers(order, ORDER_MONEY_FIELDS)
    if total_liters is not None:
        assert_liters(order["total_liters"], total_liters, "total_liters")
    for field, expected in (
        ("subtotal_cents", subtotal_cents),
        ("shipping_gross_cents", shipping_gross_cents),
        ("shipping_tiered_cents", shipping_tiered_cents),
        ("shipping_discount_cents", shipping_discount_cents),
        ("shipping_cents", shipping_cents),
        ("excise_tax_cents", excise_tax_cents),
        ("sales_tax_cents", sales_tax_cents),
        ("pre_fee_total_cents", pre_fee_total_cents),
        ("compliance_handling_fee_cents", compliance_handling_fee_cents),
        ("total_cents", total_cents),
    ):
        if expected is not None:
            assert_cents(order[field], expected, field)


def assert_canonical_order_money(order):
    """The frozen figures of the canonical 4.500 L TX order."""
    assert_charge_chain(
        order,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        subtotal_cents=CANONICAL_ORDER_SUBTOTAL_CENTS,
        shipping_cents=CANONICAL_ORDER_SHIPPING_CENTS,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        sales_tax_cents=CANONICAL_ORDER_SALES_TAX_CENTS,
        total_cents=CANONICAL_ORDER_TOTAL_CENTS,
    )


# ---------------------------------------------------------------------------
# Shipments and the ledger
# ---------------------------------------------------------------------------
def assert_tracking_number(value):
    """``TRK-`` followed by eight hexadecimal characters (PRD §3.7)."""
    assert isinstance(value, str) and TRACKING_NUMBER_RE.match(value), (
        f"tracking_number must be TRK- plus eight hex characters, got {value!r}"
    )


def assert_ledger_entry(entry, event_type=None, liters=None, state_code=None,
                        order_id=None, shipment_id=None):
    """Assert the shape of one append-only ledger row (PRD §3.4)."""
    assert_immutable_identity(entry)
    if event_type is not None:
        assert entry["event_type"] == event_type, (
            f"Expected event_type {event_type}, got {entry['event_type']}"
        )
    if liters is not None:
        assert_liters(entry["liters"], liters, "liters")
    if state_code is not None:
        assert entry["state_code"] == state_code
    if order_id is not None:
        assert entry["order_id"] == order_id
    if shipment_id is not None:
        assert entry["shipment_id"] == shipment_id


def assert_ledger_sums_to(entries, expected_total):
    total = sum(entry["liters"] for entry in entries)
    assert total == pytest.approx(expected_total, abs=LITERS_TOLERANCE), (
        f"Expected the ledger rows to sum to {expected_total:.3f}, got {total}"
    )


def sorted_ids(rows):
    return [row["id"] for row in rows]
