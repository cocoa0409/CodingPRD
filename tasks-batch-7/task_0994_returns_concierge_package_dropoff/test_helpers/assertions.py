"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BillingCycleStatus,
    CarrierRouteStatus,
    ConsolidationToteStatus,
    DropoffLocationStatus,
    ExceptionCaseStatus,
    ExceptionKind,
    ExceptionResolution,
    ItemCondition,
    LabelStatus,
    LabelType,
    LedgerEntryKind,
    LocationKind,
    LockerSlotStatus,
    MerchantStatus,
    PickupAppointmentStatus,
    PlanTier,
    RefundStatus,
    ReturnItemStatus,
    ReturnMethod,
    ReturnOrderStatus,
    ShopperStatus,
    SlotReservationStatus,
    SlotSizeClass,
    SubscriptionPlanStatus,
)


def _assert_common_fields(data: dict):
    """PRD §2.4: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_subscription_plan(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in _enum_values(PlanTier)
    for field in ("monthly_fee_cents", "included_returns", "overage_fee_cents",
                  "oversize_surcharge_cents", "pickup_fee_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer (PRD §3.1)"
        )
    for field in ("pickup_enabled", "boxless_enabled", "oversize_enabled",
                  "free_returns"):
        assert isinstance(data[field], bool)
    assert data["status"] in _enum_values(SubscriptionPlanStatus)


def assert_merchant_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in _enum_values(MerchantStatus)
    assert isinstance(data["ledger_balance_cents"], int)


def assert_billing_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["merchant_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in _enum_values(BillingCycleStatus)
    for field in ("fulfilled_count", "in_flight_count", "refunds_accrued_cents"):
        assert isinstance(data[field], int)


def assert_shopper(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["postal_code"], str) and data["postal_code"]
    assert data["status"] in _enum_values(ShopperStatus)
    assert isinstance(data["fraud_strikes"], int) and data["fraud_strikes"] >= 0


def assert_return_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["shopper_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert data["method"] in _enum_values(ReturnMethod)
    assert isinstance(data["boxless"], bool)
    assert data["status"] in _enum_values(ReturnOrderStatus)
    assert isinstance(data["refund_estimate_cents"], int)
    assert data["refund_final_cents"] is None or isinstance(data["refund_final_cents"], int)
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])
    assert data["tote_id"] is None or is_valid_uuid(data["tote_id"])
    assert data["dropoff_location_id"] is None or is_valid_uuid(data["dropoff_location_id"])
    assert isinstance(data["total_units"], int)
    assert isinstance(data["total_weight_grams"], int)
    assert isinstance(data["has_oversize_item"], bool)


def assert_return_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["return_order_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert data["declared_condition"] in _enum_values(ItemCondition)
    assert data["condition"] is None or data["condition"] in _enum_values(ItemCondition)
    assert data["longest_side_cm"] > 0
    assert isinstance(data["weight_grams"], int) and data["weight_grams"] > 0
    assert data["status"] in _enum_values(ReturnItemStatus)
    assert data["deduction_cents"] is None or isinstance(data["deduction_cents"], int)
    assert data["inspected_at"] is None or is_iso8601_timestamp(data["inspected_at"])


def assert_dropoff_location(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in _enum_values(LocationKind)
    assert isinstance(data["postal_code"], str) and data["postal_code"]
    assert data["status"] in _enum_values(DropoffLocationStatus)
    assert isinstance(data["reserved_slot_count"], int)
    assert isinstance(data["occupied_slot_count"], int)


def assert_locker_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert data["size_class"] in _enum_values(SlotSizeClass)
    assert data["status"] in _enum_values(LockerSlotStatus)


def assert_slot_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["slot_id"])
    assert is_valid_uuid(data["return_order_id"])
    assert data["status"] in _enum_values(SlotReservationStatus)
    assert is_iso8601_timestamp(data["hold_start"])
    assert is_iso8601_timestamp(data["hold_until"])
    assert data.get("label_id") is None or is_valid_uuid(data["label_id"])


def assert_label(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["return_order_id"])
    assert data["label_type"] in _enum_values(LabelType)
    assert data["status"] in _enum_values(LabelStatus)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["supersedes_label_id"] is None or is_valid_uuid(data["supersedes_label_id"])


def assert_courier_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["window_capacity"], int) and data["window_capacity"] >= 1
    assert isinstance(data["confirmed_load"], int)
    assert isinstance(data["demand_load"], int)
    assert data["demand_load"] >= data["confirmed_load"], (
        "demand_load is always at least confirmed_load (PRD §3.6)"
    )


def assert_pickup_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["return_order_id"])
    assert is_valid_uuid(data["zone_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in _enum_values(PickupAppointmentStatus)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_carrier_route(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["origin_location_id"])
    assert isinstance(data["destination_facility"], str) and data["destination_facility"]
    assert isinstance(data["weight_capacity_grams"], int) and data["weight_capacity_grams"] > 0
    assert data["status"] in _enum_values(CarrierRouteStatus)


def assert_consolidation_tote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["location_id"])
    assert data["status"] in _enum_values(ConsolidationToteStatus)
    assert isinstance(data["manifest_units"], int)
    assert isinstance(data["manifest_weight_grams"], int)
    assert data["sealed_by_user_id"] is None or isinstance(data["sealed_by_user_id"], str)


def assert_refund_ledger_entry(data: dict):
    """PRD §2.4: ledger entries carry only id and created_at — never
    updated_at or version (immutable append-only log)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert is_valid_uuid(data["return_order_id"])
    assert data["kind"] in _enum_values(LedgerEntryKind)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["note"], str)
    assert isinstance(data["actor_user_id"], str)


def assert_exception_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["return_order_id"])
    assert data["return_item_id"] is None or is_valid_uuid(data["return_item_id"])
    assert data["kind"] in _enum_values(ExceptionKind)
    assert isinstance(data["note"], str)
    assert data["status"] in _enum_values(ExceptionCaseStatus)
    assert data["resolution"] is None or data["resolution"] in _enum_values(ExceptionResolution)
    assert isinstance(data["opened_by_user_id"], str)
    assert data["resolved_by_user_id"] is None or isinstance(data["resolved_by_user_id"], str)
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0


def assert_refund_projection(data: dict):
    assert isinstance(data["estimated_cents"], int)
    assert data["final_cents"] is None or isinstance(data["final_cents"], int)
    assert isinstance(data["payable_cents"], int)
    assert isinstance(data["entry_count"], int)
    assert data["refund_status"] in _enum_values(RefundStatus)


def assert_charge_preview(data: dict):
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    for field in ("fulfilled_count", "in_flight_count", "base_cents", "overage_count",
                  "overage_fee_cents", "surcharge_cents", "gross_cents",
                  "discount_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
