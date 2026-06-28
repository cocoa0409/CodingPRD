"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _check_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _check_versioned(data: dict):
    _check_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _check_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["carrier_account_number"], str) and len(data["carrier_account_number"]) > 0
    assert data["risk_flag"] in ("GREEN", "WATCH", "BLOCKED")
    assert isinstance(data["lifetime_approved_claim_count"], int)
    assert data["lifetime_approved_claim_count"] >= 0


def assert_plan(data: dict):
    _check_common(data)
    # write-once reference: no updated_at / version
    assert "updated_at" not in data, "Plan must not carry updated_at"
    assert "version" not in data, "Plan must not carry version"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    for f in ("monthly_premium_cents", "base_deductible_cents",
              "loss_deductible_multiplier_bps", "annual_claim_limit",
              "replacement_value_cap_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_replacement_sku(data: dict):
    _check_common(data)
    assert "updated_at" not in data, "ReplacementSku must not carry updated_at"
    assert "version" not in data, "ReplacementSku must not carry version"
    assert isinstance(data["model_name"], str) and len(data["model_name"]) > 0
    for f in ("msrp_cents", "depreciation_rate_bps_per_month", "stock_on_hand"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_enrollment(data: dict):
    _check_versioned(data)
    assert data["status"] in ("PENDING_ELIGIBILITY", "ACTIVE", "SUSPENDED", "CANCELLED")
    assert isinstance(data["imei"], str)
    assert isinstance(data["premium_paid_through_cycle"], int)


def assert_premium_invoice(data: dict):
    _check_versioned(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    assert isinstance(data["cycle_index"], int)
    assert isinstance(data["amount_cents"], int)


def assert_claim(data: dict):
    _check_versioned(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "ROUTED_REPAIR",
                              "ROUTED_REPLACE", "FULFILLED", "DENIED", "WITHDRAWN")
    assert data["peril"] in ("CRACKED", "LOST", "THEFT")
    assert isinstance(data["deductible_cents"], int)
    assert isinstance(data["replacement_value_cents"], int)
    assert isinstance(data["net_payout_cents"], int)


def assert_fraud_screen(data: dict):
    _check_common(data)
    assert "updated_at" not in data, "FraudScreen must not carry updated_at"
    assert "version" not in data, "FraudScreen must not carry version"
    assert data["outcome"] in ("PASS", "REVIEW", "BLOCK")
    assert isinstance(data["velocity_count"], int)


def assert_repair_order(data: dict):
    _check_versioned(data)
    assert data["status"] in ("OPEN", "COMPLETED", "CANCELLED")
    assert isinstance(data["repair_cost_cents"], int)


def assert_advanced_exchange(data: dict):
    _check_versioned(data)
    assert data["status"] in ("RESERVED", "SHIPPED", "DELIVERED", "RETURN_DUE", "CLOSED", "CANCELLED")
    assert isinstance(data["nonreturn_fee_cents"], int)


def assert_trade_in(data: dict):
    _check_versioned(data)
    assert data["status"] in ("RECEIVED", "GRADED", "CREDITED", "RECYCLED")
    assert data["condition_grade"] in ("A", "B", "C", "EWASTE")
    assert isinstance(data["credit_cents"], int)
