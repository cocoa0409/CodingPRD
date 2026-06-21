"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id, created_at, updated_at, version for common_fields:true entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["fico_score"], int)
    assert 300 <= data["fico_score"] <= 850
    assert data["fico_tier"] in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) > 0
    assert isinstance(data["make_model"], str)
    assert isinstance(data["msrp_cents"], int)
    assert isinstance(data["sale_price_cents"], int)
    assert isinstance(data["residual_value_cents"], int)
    assert data["status"] in ("AVAILABLE", "FINANCED")


def assert_rate_card(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["active"], bool)


def assert_loan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["down_payment_cents"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["gap_insurance"], bool)
    assert isinstance(data["financed_principal_cents"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["payments_made_count"], int)
    assert isinstance(data["principal_balance_cents"], int)
    assert isinstance(data["missed_payment_count"], int)
    assert data["status"] in ("CURRENT", "DELINQUENT", "DEFAULT", "PAID_OFF")


def assert_lease(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["term_months"], int)
    assert isinstance(data["base_monthly_cents"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert data["status"] in (
        "ACTIVE", "MATURING", "RETURNED", "PURCHASED", "RENEWED", "SETTLED",
    )


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["election"] in ("RETURN", "PURCHASE", "RENEW")
    assert isinstance(data["total_due_cents"], int)
    assert data["status"] == "FINALIZED"


def assert_payment(data: dict):
    """Payment is append-only (common_fields:false): id + created_at, NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Payment must not carry a version field"
    assert "updated_at" not in data, "Payment must not carry an updated_at field"
    assert data["kind"] in ("SCHEDULED", "LATE_FEE", "PAYOFF")
    assert data["status"] in ("POSTED", "MISSED")
