"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_facility(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["climate_premium_pct"], (int, float))
    assert 0 <= data["climate_premium_pct"] <= 1
    assert isinstance(data["lien_default_days"], int)
    assert isinstance(data["late_fee_grace_days"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["occupied_unit_count"], int) and data["occupied_unit_count"] >= 0


def assert_unit(data: dict):
    _common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["unit_number"], str)
    assert data["size_class"] in ("SIZE_5X5", "SIZE_10X10", "SIZE_10X20")
    assert isinstance(data["climate_controlled"], bool)
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] > 0
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "VACATING")
    assert data["current_lease_id"] is None or is_valid_uuid(data["current_lease_id"])


def assert_tenant(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["state_code"], str)


def assert_lease(data: dict):
    _common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert data["status"] in (
        "PENDING", "ACTIVE", "DELINQUENT", "PRE_LIEN", "LIEN",
        "AUCTION_SCHEDULED", "AUCTIONED", "TRANSFERRED", "CLOSED",
    )
    assert isinstance(data["billing_day"], int) and 1 <= data["billing_day"] <= 28
    assert isinstance(data["insurance_required"], bool)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["days_past_due"], int) and data["days_past_due"] >= 0


def assert_invoice(data: dict):
    _common(data)
    assert is_valid_uuid(data["lease_id"])
    for f in ("base_amount_cents", "climate_amount_cents", "insurance_amount_cents",
              "late_fee_cents", "total_amount_cents", "amount_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["status"] in ("OPEN", "PARTIAL", "OVERDUE", "PAID", "WAIVED")
    assert (data["total_amount_cents"]
            == data["base_amount_cents"] + data["climate_amount_cents"]
            + data["insurance_amount_cents"] + data["late_fee_cents"]), \
        "total must equal base + climate + insurance + late_fee"


def assert_payment(data: dict):
    _common(data)
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("APPLIED", "REVERSED")
    assert isinstance(data["allocation"], list)
    assert isinstance(data["overpay_credit_cents"], int) and data["overpay_credit_cents"] >= 0


def assert_ledger_entry(data: dict):
    # common_fields: false — only id + created_at, NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["lease_id"])
    assert data["entry_type"] in (
        "CHARGE", "LATE_FEE", "PAYMENT", "CREDIT", "REVERSAL", "AUCTION_SETTLEMENT",
    )
    assert isinstance(data["amount_cents"], int)
    assert data["source_type"] in ("INVOICE", "PAYMENT", "AUCTION", "MANUAL")


def assert_insurance_policy(data: dict):
    _common(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["coverage_tier"] in ("BASIC", "STANDARD", "PREMIUM")
    assert isinstance(data["coverage_limit_cents"], int)
    assert isinstance(data["monthly_premium_cents"], int)
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED")


def assert_auction_proceeding(data: dict):
    _common(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["status"] in (
        "NOTICE_SENT", "LIEN_FILED", "SCHEDULED", "SOLD", "REDEEMED", "CANCELLED",
    )
    assert isinstance(data["redemption_amount_cents"], int)


def assert_transfer_order(data: dict):
    _common(data)
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["from_unit_id"])
    assert is_valid_uuid(data["to_unit_id"])
    assert data["status"] in ("REQUESTED", "COMPLETED", "CANCELLED")
