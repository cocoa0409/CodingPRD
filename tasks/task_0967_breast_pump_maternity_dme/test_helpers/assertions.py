"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["shipping_address"], str)
    assert isinstance(data["out_of_pocket_balance_cents"], int)
    assert isinstance(data["oop_accumulated_cents"], int)
    assert data["next_resupply_date"] is None or isinstance(data["next_resupply_date"], str)
    assert isinstance(data["active_schedule_count"], int)


def assert_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["plan_type"] in ("COMMERCIAL_PPO", "MEDICAID", "MEDICARE_ADVANTAGE")
    assert isinstance(data["benefit_period_start"], str)
    assert isinstance(data["benefit_period_end"], str)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["pumps_consumed_count"], int)
    assert isinstance(data["garments_consumed_count"], int)
    assert isinstance(data["deductible_met_cents"], int)


def assert_prescription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["pump_type"] in ("SINGLE_ELECTRIC", "DOUBLE_ELECTRIC", "HOSPITAL_GRADE")
    assert data["status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "CONSUMED", "EXPIRED"
    )


def assert_catalog_item(data: dict):
    _assert_common(data)
    assert data["item_type"] in ("PUMP", "PART", "COMPRESSION_GARMENT")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["unit_price_cents"], int)


def assert_pump_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("policy_id", ""))
    assert is_valid_uuid(data.get("prescription_id", ""))
    assert is_valid_uuid(data.get("pump_item_id", ""))
    assert data["fulfillment_status"] in (
        "PENDING_QUALIFICATION", "QUALIFIED", "SHIPPED", "DELIVERED", "CANCELLED"
    )
    assert data["billing_status"] in (
        "UNBILLED", "AUTH_PENDING", "AUTH_APPROVED", "CLAIM_FILED", "ADJUDICATED", "DENIED"
    )
    assert isinstance(data["merchandise_subtotal_cents"], int)
    assert isinstance(data["discount_total_cents"], int)
    assert isinstance(data["order_total_cents"], int)
    assert isinstance(data["replacement_count"], int)
    assert isinstance(data["warranty_blocked"], bool)


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("catalog_item_id", ""))
    assert data["line_type"] in ("PUMP_PRIMARY", "ADDON_GARMENT")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["discount_cents"], int)


def assert_prior_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pump_order_id", ""))
    assert data["status"] in (
        "SUBMITTED", "PENDED", "APPROVED", "DENIED", "APPEALED",
        "DENIED_FINAL", "EXPIRED", "WITHDRAWN",
    )
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 1


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier"], str)
    assert isinstance(data["tracking_number"], str)
    assert data["status"] in (
        "LABEL_CREATED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED", "RETURNED", "LOST"
    )
    assert isinstance(data["is_warranty_replacement"], bool)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "ADJUDICATED", "DENIED", "APPEALED", "VOID")
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert isinstance(data["submitted_by_user_id"], str)


def assert_resupply_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("pump_order_id", ""))
    assert is_valid_uuid(data.get("catalog_item_id", ""))
    assert isinstance(data["frequency_days"], int)
    assert data["schedule_mode"] in ("ROLLING", "CALENDAR_ANCHORED")
    assert isinstance(data["anchor_date"], str)
    assert data["last_fulfilled_date"] is None or isinstance(data["last_fulfilled_date"], str)
    assert isinstance(data["next_eligible_date"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "ENDED")


def assert_resupply_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("schedule_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("APPROVED", "SHIPPED", "DELIVERED", "CANCELLED")


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pump_order_id", ""))
    assert data["issue_type"] in (
        "MOTOR_FAILURE", "BATTERY_FAILURE", "SUCTION_LOSS", "PHYSICAL_DAMAGE", "OTHER"
    )
    assert data["status"] in (
        "OPENED", "APPROVED_REPAIR", "APPROVED_REPLACE", "DENIED", "RESOLVED"
    )
    assert isinstance(data["reopen_count"], int)


def assert_member_balance_invariants(member: dict):
    """Member ledger aggregates are never negative (PRD §3.6 remit/void arithmetic)."""
    assert member["out_of_pocket_balance_cents"] >= 0
    assert member["oop_accumulated_cents"] >= 0


def assert_policy_consumption_invariants(policy: dict):
    """Per-period consumption counters stay within declared allowances (PRD §2.7)."""
    assert 0 <= policy["pumps_consumed_count"] <= policy["pump_allowance_per_period"]
    assert 0 <= policy["garments_consumed_count"]
    assert policy["deductible_met_cents"] >= 0
