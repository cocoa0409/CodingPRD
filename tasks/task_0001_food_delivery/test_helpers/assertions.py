"""Entity assertions and domain invariant checkers for the food delivery platform."""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AssignmentStatus,
    FineReason,
    FineSettlementStatus,
    FineSubjectType,
    OrderStatus,
    PaymentStatus,
    RestaurantStatus,
    ReturnReason,
    ReturnStatus,
    RiderBonusTier,
    RiderStatus,
    RouteGroupStatus,
    WorkOrderCategory,
    WorkOrderOpenedByRole,
    WorkOrderStatus,
)


# ──────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────

def _assert_id_and_created(data: Dict[str, Any]) -> None:
    """PRD §2.4: every resource carries id (UUID) and created_at (ISO 8601 UTC)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_common_audit(data: Dict[str, Any]) -> None:
    """PRD §2.4: standard audit trail — id, created_at, updated_at, version."""
    _assert_id_and_created(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def _enum_values(enum_cls) -> list:
    return [m.value for m in enum_cls]


# ──────────────────────────────────────────────────────────
# Entity assertions
# ──────────────────────────────────────────────────────────

def assert_restaurant(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str)
    assert isinstance(data["lat"], (int, float))
    assert isinstance(data["lng"], (int, float))
    assert data["status"] in _enum_values(RestaurantStatus), f"bad status: {data['status']!r}"
    assert "commission_rate_override" in data, "commission_rate_override must be in response"
    override = data["commission_rate_override"]
    if override is not None:
        assert isinstance(override, (int, float))
        assert 0.05 <= override <= 0.35, f"commission_rate_override out of range: {override}"
    assert isinstance(data["pending_settlement_cents"], int)


def assert_rider(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["phone"], str) and len(data["phone"]) > 0
    assert data["status"] in _enum_values(RiderStatus), f"bad status: {data['status']!r}"
    for metric in ("on_time_rate", "acceptance_rate"):
        assert isinstance(data[metric], (int, float))
        assert 0.0 <= data[metric] <= 1.0, f"{metric} out of range"
    assert isinstance(data["rating"], (int, float))
    assert 0.0 <= data["rating"] <= 5.0, "rating must be in [0,5]"
    assert data["bonus_tier"] in _enum_values(RiderBonusTier), f"bad bonus_tier: {data['bonus_tier']!r}"
    assert isinstance(data["wallet_balance_cents"], int)


def assert_customer(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["phone"], str) and len(data["phone"]) > 0
    assert isinstance(data["address"], str)
    assert isinstance(data["lat"], (int, float))
    assert isinstance(data["lng"], (int, float))
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0, "credit_balance_cents is non-negative per PRD §3.2"
    assert isinstance(data["trust_score"], (int, float))
    assert 0.0 <= data["trust_score"] <= 1.0


def assert_menu_item(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["price_cents"], int)
    assert 1 <= data["price_cents"] <= 1_000_000
    assert isinstance(data["is_listed"], bool)


def assert_order(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["restaurant_id"], str)
    assert data["status"] in _enum_values(OrderStatus), f"bad status: {data['status']!r}"
    assert isinstance(data["items"], list) and len(data["items"]) > 0
    for entry in data["items"]:
        assert isinstance(entry.get("menu_item_id"), str)
        assert isinstance(entry.get("quantity"), int) and entry["quantity"] >= 1
        assert isinstance(entry.get("unit_price_cents"), int) and entry["unit_price_cents"] >= 1
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 100
    assert isinstance(data["distance_km"], (int, float)) and data["distance_km"] >= 0
    assert isinstance(data["is_peak"], bool)
    assert isinstance(data["provisional_delivery_fee_cents"], int)
    assert isinstance(data["provisional_commission_cents"], int)
    assert data["payment_status"] in _enum_values(PaymentStatus), (
        f"bad payment_status: {data['payment_status']!r}"
    )
    assert is_iso8601_timestamp(data["promised_delivery_time"]), (
        "promised_delivery_time must be ISO 8601"
    )
    # final_* and actual_delivery_time may be null pre-delivery per PRD §3.4.


def assert_assignment(data: Dict[str, Any]) -> None:
    # Append-only: PRD §2.4 — only id + created_at. No updated_at, no version.
    _assert_id_and_created(data)
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "Assignment must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "Assignment must not expose version per PRD §2.4"
    )
    assert isinstance(data["order_id"], str)
    assert isinstance(data["rider_id"], str)
    assert data["status"] in _enum_values(AssignmentStatus), f"bad status: {data['status']!r}"
    assert is_iso8601_timestamp(data["offered_at"]), "offered_at must be ISO 8601"


def assert_route_group(data: Dict[str, Any]) -> None:
    _assert_id_and_created(data)
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "RouteGroup must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "RouteGroup must not expose version per PRD §2.4"
    )
    assert isinstance(data["rider_id"], str)
    assert isinstance(data["assignment_ids"], list)
    assert data["status"] in _enum_values(RouteGroupStatus), f"bad status: {data['status']!r}"


def assert_fine(data: Dict[str, Any]) -> None:
    _assert_id_and_created(data)
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "Fine must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "Fine must not expose version per PRD §2.4"
    )
    assert data["subject_type"] in _enum_values(FineSubjectType), (
        f"bad subject_type: {data['subject_type']!r}"
    )
    assert isinstance(data["subject_id"], str)
    assert data["reason"] in _enum_values(FineReason), f"bad reason: {data['reason']!r}"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["settlement_status"] in _enum_values(FineSettlementStatus), (
        f"bad settlement_status: {data['settlement_status']!r}"
    )


def assert_return(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["order_id"], str)
    assert data["reason"] in _enum_values(ReturnReason), f"bad reason: {data['reason']!r}"
    assert isinstance(data["requested_refund_cents"], int) and data["requested_refund_cents"] >= 1
    assert data["status"] in _enum_values(ReturnStatus), f"bad status: {data['status']!r}"
    # approved_refund_cents may be null while REQUESTED; must be positive int once decided.


def assert_work_order(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert data["opened_by_role"] in _enum_values(WorkOrderOpenedByRole), (
        f"bad opened_by_role: {data['opened_by_role']!r}"
    )
    assert isinstance(data["opened_by_id"], str)
    assert data["category"] in _enum_values(WorkOrderCategory), (
        f"bad category: {data['category']!r}"
    )
    assert data["status"] in _enum_values(WorkOrderStatus), f"bad status: {data['status']!r}"
