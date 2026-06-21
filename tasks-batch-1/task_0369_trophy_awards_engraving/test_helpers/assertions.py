"""Entity assertions and domain invariant checkers for the Trophy, Awards & Engraving API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

PRODUCTION_STATES = [
    "DRAFT", "PRICED", "CONFIRMED", "IN_PRODUCTION", "READY", "FULFILLED", "CANCELLED",
]
PAYMENT_STATES = ["UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"]
PROOF_STATES = ["DRAFT", "SENT", "APPROVED", "CHANGES_REQUESTED"]
LINE_STATES = ["PENDING", "ALLOCATED", "ENGRAVING", "ASSEMBLED"]
ALLOC_STATES = ["RESERVED", "CONSUMED", "RELEASED"]
FULFILLMENT_STATES = ["STAGED", "HANDED_OFF"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_full_audit(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version must start at 1"


def assert_customer(data: dict):
    _assert_full_audit(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["lifetime_completed_orders"], int)
    # on_time_rate_pct is null until first FULFILLED order.
    assert data.get("on_time_rate_pct") is None or isinstance(
        data["on_time_rate_pct"], (int, float)
    )


def assert_component(data: dict):
    _assert_full_audit(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["allocated_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert isinstance(data["low_stock"], bool)
    assert_component_invariants(data)


def assert_component_invariants(data: dict):
    """Stock invariant: available_qty == on_hand_qty - allocated_qty and never negative."""
    assert data["available_qty"] >= 0, "available_qty must never be negative"
    assert data["available_qty"] == data["on_hand_qty"] - data["allocated_qty"], (
        "available_qty must equal on_hand_qty - allocated_qty"
    )
    assert data["low_stock"] == (data["available_qty"] <= data["reorder_point"]), (
        "low_stock must be true iff available_qty <= reorder_point"
    )


def assert_order(data: dict):
    _assert_full_audit(data)
    assert data["production_status"] in PRODUCTION_STATES, (
        f"bad production_status {data['production_status']!r}"
    )
    assert data["payment_status"] in PAYMENT_STATES, (
        f"bad payment_status {data['payment_status']!r}"
    )
    assert isinstance(data["line_count"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_order_line(data: dict):
    _assert_full_audit(data)
    assert data["line_status"] in LINE_STATES, f"bad line_status {data['line_status']!r}"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["assembled_count"], int)


def assert_proof(data: dict):
    _assert_full_audit(data)
    assert data["proof_status"] in PROOF_STATES, f"bad proof_status {data['proof_status']!r}"
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 1


def assert_component_allocation(data: dict):
    _assert_full_audit(data)
    assert data["alloc_status"] in ALLOC_STATES, f"bad alloc_status {data['alloc_status']!r}"
    assert isinstance(data["qty"], int) and data["qty"] >= 1


def assert_fulfillment(data: dict):
    _assert_full_audit(data)
    assert data["fulfillment_status"] in FULFILLMENT_STATES
    assert isinstance(data["ship_fee_cents"], int)


def assert_payment(data: dict):
    """Payment is append-only: id + created_at only, no updated_at, no version."""
    _assert_common(data)
    assert "version" not in data, "Payment must NOT carry a version field"
    assert "updated_at" not in data, "Payment must NOT carry an updated_at field"
    assert data["pay_status"] in ["CAPTURED", "REFUNDED"]
