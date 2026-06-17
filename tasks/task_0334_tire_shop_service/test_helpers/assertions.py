"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

_TPMS = {"DIRECT", "INDIRECT", "NONE"}
_SPEED = {"S", "T", "H", "V", "W", "Y"}
_TIRE_STATUS = {"ACTIVE", "DISCONTINUED"}
_GRADE = {"OE_EXACT", "APPROVED_PLUS", "NOT_RECOMMENDED"}
_BAY_STATUS = {"OPEN", "OUT_OF_SERVICE"}
_FULFILLMENT = {"DRAFT", "APPROVED", "IN_SERVICE", "COMPLETED", "CANCELLED"}
_PAYMENT = {"UNPAID", "AUTHORIZED", "PAID", "REFUNDED"}
_LINE_TYPE = {"TIRE", "MOUNT_BALANCE", "ROTATION", "TPMS_SERVICE", "ALIGNMENT"}
_LINE_STATUS = {"PENDING", "COMMITTED", "VOID"}
_RH_STATUS = {"PENDING", "ACTIVE", "CLAIMED", "VOID"}
_APPT_STATUS = {"SCHEDULED", "RESCHEDULE_PENDING", "CHECKED_IN", "COMPLETED", "CANCELLED"}
_SO_STATUS = {"ORDERED", "RECEIVED", "BACKORDER_CANCELLED"}
_CLAIM_STATUS = {"SUBMITTED", "APPROVED", "REJECTED", "PAID"}
_PAYOUT = {"STORE_CREDIT", "REFUND"}


def _assert_audit_triad(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_audit_triad(data)
    assert isinstance(data["email"], str) and data["email"], "email must be non-empty"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents must never be negative"


def assert_vehicle(data: dict):
    _assert_audit_triad(data)
    assert is_valid_uuid(data["customer_id"]), "customer_id must be a UUID"
    assert isinstance(data["model_year"], int)
    assert 1980 <= data["model_year"] <= 2030
    assert 13 <= data["rim_diameter_in"] <= 24
    assert data["tpms_type"] in _TPMS


def assert_tire_model(data: dict):
    _assert_audit_triad(data)
    assert 70 <= data["load_index"] <= 130
    assert data["speed_rating"] in _SPEED
    assert data["unit_price_cents"] >= 0
    assert data["mileage_warranty_miles"] >= 0
    assert 6 <= data["original_tread_32nds"] <= 14
    assert data["stock_qty"] >= 0, "stock_qty must never be negative"
    assert data["status"] in _TIRE_STATUS


def assert_fitment_rule(data: dict):
    """FitmentRule has common_fields:false — only id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "FitmentRule is immutable; must not carry updated_at"
    assert "version" not in data, "FitmentRule is immutable; must not carry version"
    assert data["fitment_grade"] in _GRADE


def assert_service_bay(data: dict):
    _assert_audit_triad(data)
    assert isinstance(data["alignment_capable"], bool)
    assert 0 <= data["turnover_buffer_min"] <= 60
    assert data["status"] in _BAY_STATUS


def assert_work_order(data: dict):
    _assert_audit_triad(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["fulfillment_status"] in _FULFILLMENT
    assert data["payment_status"] in _PAYMENT
    for fld in ("store_credit_applied_cents", "parts_subtotal_cents",
                "service_subtotal_cents", "disposal_fee_cents",
                "road_hazard_premium_cents", "tax_cents", "total_due_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"
    assert data["total_due_cents"] >= 0, "total_due_cents must never be negative"


def assert_work_order_line(data: dict):
    _assert_audit_triad(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["line_type"] in _LINE_TYPE
    assert data["quantity"] >= 1
    assert data["line_status"] in _LINE_STATUS
    assert isinstance(data["unit_price_cents_snapshot"], int)
    assert isinstance(data["extended_cents"], int)
    assert isinstance(data["road_hazard_opted"], bool)


def assert_road_hazard_warranty(data: dict):
    _assert_audit_triad(data)
    assert is_valid_uuid(data["work_order_line_id"])
    assert is_valid_uuid(data["tire_model_id"])
    assert data["status"] in _RH_STATUS
    assert isinstance(data["premium_cents"], int)
    assert isinstance(data["covered_quantity"], int)


def assert_install_appointment(data: dict):
    _assert_audit_triad(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["service_bay_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["requires_alignment"], bool)
    assert data["status"] in _APPT_STATUS


def assert_special_order(data: dict):
    _assert_audit_triad(data)
    assert is_valid_uuid(data["work_order_line_id"])
    assert is_valid_uuid(data["tire_model_id"])
    assert data["requested_quantity"] >= 1
    assert isinstance(data["deposit_cents"], int)
    assert data["status"] in _SO_STATUS


def assert_mileage_warranty_claim(data: dict):
    _assert_audit_triad(data)
    assert is_valid_uuid(data["work_order_line_id"])
    assert is_valid_uuid(data["tire_model_id"])
    assert data["measured_tread_32nds"] >= 2
    assert data["miles_driven"] >= 0
    assert data["payout_method"] in _PAYOUT
    assert data["claim_quantity"] >= 1
    assert data["status"] in _CLAIM_STATUS
    assert isinstance(data["prorated_credit_cents"], int)
