"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. All money fields are integer cents.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["customer_name"], str) and len(data["customer_name"]) > 0
    assert data["lifecycle_status"] in ["PROSPECT", "ACTIVE", "SUSPENDED", "CANCELLED"]
    assert data["promo_status"] in ["NONE", "PROMO_ACTIVE", "ROLLED_BACK"]
    assert isinstance(data["tenure_months"], int) and data["tenure_months"] >= 0
    assert isinstance(data["regional_sports_fee_cents"], int)
    assert data["regional_sports_fee_cents"] >= 0
    assert isinstance(data["monthly_recurring_cents"], int)
    assert data["monthly_recurring_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["PENDING", "ACTIVE", "DOWNGRADED", "SUPERSEDED", "TERMINATED"]
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_add_on(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "DROPPED"]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    if data["status"] == "ACTIVE":
        assert data.get("drop_reason") is None, "ACTIVE add-on must have null drop_reason"
    else:
        assert data["drop_reason"] in ["USER", "INCOMPATIBLE_DOWNGRADE", "CANCELLED"]


def assert_equipment_lease(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ASSIGNED", "RETURNED", "UNRETURNED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["monthly_lease_cents"], int) and data["monthly_lease_cents"] >= 0
    assert isinstance(data["unreturned_charge_cents"], int) and data["unreturned_charge_cents"] >= 0


def assert_service_visit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["visit_type"] in ["INSTALL", "SERVICE"]
    assert data["status"] in ["SCHEDULED", "DISPATCHED", "COMPLETED", "NO_SHOW", "CANCELLED"]
    assert isinstance(data["truck_roll_fee_cents"], int) and data["truck_roll_fee_cents"] >= 0


def assert_promotion_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "ROLLED_BACK", "CANCELLED"]
    assert isinstance(data["applied_at_tenure"], int)
    assert isinstance(data["rollback_at_tenure"], int)
    assert isinstance(data["is_winback"], bool)


def assert_billing_statement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["proration_mode"] in ["FULL_CYCLE", "PRORATED"]
    assert data["status"] in ["DRAFT", "ISSUED", "VOID"]
    for line in (
        "package_charge_cents", "addon_charge_cents", "equipment_charge_cents",
        "regional_sports_fee_cents", "visit_charge_cents", "promo_discount_cents",
        "etf_charge_cents", "total_cents",
    ):
        assert isinstance(data[line], int), f"{line} must be integer cents"
        assert data[line] >= 0, f"{line} must be >= 0"


def assert_channel_package(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["tier_code"] in ["BASIC", "PLUS", "PREMIER"]
    assert isinstance(data["rank"], int) and 1 <= data["rank"] <= 3
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
