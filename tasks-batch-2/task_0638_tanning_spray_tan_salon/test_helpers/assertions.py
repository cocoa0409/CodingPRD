"""Entity assertions and domain invariant checkers.

Audit-tracked entities (Member, Equipment, SprayRoom, Session, Product,
RetailOrder, SalonLedger) carry id + created_at + updated_at + version.
Write-once records (MembershipPlan, ConsentRecord, Payment, MaintenanceLog)
carry ONLY id + created_at — they MUST NOT carry updated_at or version.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_audit_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_write_once_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "write-once record must NOT carry updated_at"
    assert "version" not in data, "write-once record must NOT carry version"


# ---------------------------------------------------------------------------
# Write-once records
# ---------------------------------------------------------------------------
def assert_membership_plan(data: dict):
    _assert_write_once_fields(data)
    assert data["tier_code"] in ["BASIC", "PREMIUM", "UNLIMITED"]
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0


def assert_consent_record(data: dict):
    _assert_write_once_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert isinstance(data["guardian_name"], str)
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_payment(data: dict):
    _assert_write_once_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert data["kind"] in ["EFT_DUES", "RETAIL", "UPGRADE"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["outcome"] in ["SUCCEEDED", "DECLINED"]


def assert_maintenance_log(data: dict):
    _assert_write_once_fields(data)
    assert is_valid_uuid(data.get("equipment_id", "")), "equipment_id must be a valid UUID"
    assert data["reason"] in ["SCHEDULED_THRESHOLD", "MANUAL"]
    assert isinstance(data["sessions_at_service"], int)


# ---------------------------------------------------------------------------
# Audit-tracked entities
# ---------------------------------------------------------------------------
def assert_member(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["skin_type"] in ["I", "II", "III", "IV", "V", "VI"]
    assert data["status"] in ["PENDING", "ACTIVE", "FROZEN", "CANCELLED"]
    assert data["billing_status"] in ["CURRENT", "PAST_DUE", "SUSPENDED"]
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["completed_uv_session_count"], int)
    assert isinstance(data["account_credit_cents"], int)


def assert_equipment(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["kind"] in ["BED", "BOOTH"]
    assert isinstance(data["max_exposure_seconds"], int) and data["max_exposure_seconds"] >= 1
    assert isinstance(data["turnaround_seconds"], int)
    assert data["status"] in ["AVAILABLE", "IN_USE", "MAINTENANCE", "RETIRED"]
    assert isinstance(data["sessions_since_service"], int)


def assert_spray_room(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ventilation_buffer_seconds"], int)
    assert data["status"] in ["AVAILABLE", "IN_USE", "MAINTENANCE", "RETIRED"]


def assert_session(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert data["kind"] in ["UV", "SPRAY"]
    assert data["booking_mode"] in ["RESERVATION", "WALK_IN"]
    assert isinstance(data["requested_seconds"], int) and data["requested_seconds"] >= 1
    assert data["status"] in ["RESERVED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"


def assert_product(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["stock_on_hand"], int)
    assert isinstance(data["units_sold"], int)


def assert_retail_order(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert isinstance(data["lines"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["charged_cents"], int)
    assert data["status"] in ["PAID", "REFUNDED"]


def assert_salon_ledger(data: dict):
    _assert_audit_fields(data)
    assert data["singleton_key"] == "SALON", "singleton_key must equal 'SALON'"
    assert isinstance(data["deferred_revenue_cents"], int)
    assert isinstance(data["collected_dues_cents"], int)
    assert isinstance(data["collected_retail_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_product_stock_invariant(data: dict):
    """PRD §3.9: stock_on_hand + units_sold always equals initial_stock."""
    assert data["stock_on_hand"] + data["units_sold"] == data["initial_stock"], (
        "stock_on_hand + units_sold must equal initial_stock; got "
        f"{data['stock_on_hand']} + {data['units_sold']} != {data['initial_stock']}"
    )
