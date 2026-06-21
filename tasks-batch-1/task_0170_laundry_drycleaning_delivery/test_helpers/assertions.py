"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

from .types import (
    OrderStatus, GarmentStatus, ServiceType, ClaimStatus, ClaimSubjectKind,
    SubscriptionStatus, CustomerStatus, RouteWindowKind, RouteWindowStatus,
    LockerStatus, LockerAssignmentStatus, InvoiceStatus, HandoffMethod,
    PlanTier, NoteKind,
)

_VERSIONED_COMMON = ("id", "created_at", "updated_at", "version")


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_subscription_plan(data: dict):
    _assert_common_versioned(data)
    assert data["tier"] in [t.value for t in PlanTier]
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_wash_fold_grams"], int) and data["included_wash_fold_grams"] >= 0
    assert isinstance(data["overage_rate_cents_per_kg"], int) and data["overage_rate_cents_per_kg"] >= 0
    assert 0.0 <= data["dryclean_discount_pct"] <= 0.5
    assert isinstance(data["rush_waived"], bool)
    assert isinstance(data["active"], bool)


def assert_customer(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["default_address"], str)
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["risk_score"], int) and data["risk_score"] >= 0
    assert data["status"] in [s.value for s in CustomerStatus]


def assert_subscription(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["cycle_wash_fold_grams_used"], int) and data["cycle_wash_fold_grams_used"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int) and data["outstanding_balance_cents"] >= 0
    assert data["status"] in [s.value for s in SubscriptionStatus]


def assert_route_window(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["zone_code"], str)
    assert data["window_kind"] in [k.value for k in RouteWindowKind]
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert isinstance(data["stop_capacity"], int) and data["stop_capacity"] >= 1
    assert isinstance(data["booked_stops"], int)
    assert 0 <= data["booked_stops"] <= data["stop_capacity"]
    assert data["status"] in [s.value for s in RouteWindowStatus]


def assert_locker(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["location_label"], str)
    assert isinstance(data["compartment_count"], int) and data["compartment_count"] >= 1
    assert isinstance(data["hold_buffer_minutes"], int) and data["hold_buffer_minutes"] >= 0
    assert data["status"] == LockerStatus.OPEN.value


def assert_order(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["pickup_window_id"])
    assert is_valid_uuid(data["delivery_window_id"])
    assert data["handoff_method"] in [h.value for h in HandoffMethod]
    assert isinstance(data["rush"], bool)
    assert isinstance(data["estimate_total_cents"], int) and data["estimate_total_cents"] >= 0
    assert isinstance(data["final_total_cents"], int) and data["final_total_cents"] >= 0
    assert isinstance(data["risk_flag"], bool)
    assert data["status"] in [s.value for s in OrderStatus]


def assert_garment(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["order_id"])
    assert data["service_type"] in [s.value for s in ServiceType]
    assert isinstance(data["declared_weight_grams"], int) and data["declared_weight_grams"] >= 0
    assert isinstance(data["declared_piece_count"], int) and data["declared_piece_count"] >= 0
    assert isinstance(data["actual_weight_grams"], int) and data["actual_weight_grams"] >= 0
    assert isinstance(data["actual_piece_count"], int) and data["actual_piece_count"] >= 0
    assert isinstance(data["estimate_line_cents"], int) and data["estimate_line_cents"] >= 0
    assert isinstance(data["final_line_cents"], int) and data["final_line_cents"] >= 0
    assert data["status"] in [s.value for s in GarmentStatus]


def assert_locker_assignment(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["locker_id"])
    assert isinstance(data["compartment_index"], int) and data["compartment_index"] >= 1
    assert is_iso8601_timestamp(data["hold_start_utc"])
    assert is_iso8601_timestamp(data["hold_end_utc"])
    assert data["status"] in [s.value for s in LockerAssignmentStatus]


def assert_claim(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["order_id"])
    assert data["subject_kind"] in [k.value for k in ClaimSubjectKind]
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 1
    assert isinstance(data["settlement_cents"], int) and data["settlement_cents"] >= 0
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0
    assert data["status"] in [s.value for s in ClaimStatus]


def assert_invoice(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0
    assert isinstance(data["subscription_credit_cents"], int) and data["subscription_credit_cents"] >= 0
    assert isinstance(data["wallet_applied_cents"], int) and data["wallet_applied_cents"] >= 0
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert data["status"] in [s.value for s in InvoiceStatus]


def assert_garment_note_shape(data: dict):
    """A GarmentNote is append-only: id + created_at only, never version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "note id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "note created_at must be ISO 8601"
    assert "version" not in data, "GarmentNote must NOT carry a version field"
    assert "updated_at" not in data, "GarmentNote must NOT carry an updated_at field"
    assert data["note_kind"] in [k.value for k in NoteKind]
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 10
