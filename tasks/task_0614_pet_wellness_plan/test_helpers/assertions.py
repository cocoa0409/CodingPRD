"""Entity assertions and domain invariant checkers.

Validate response structures against the Pet Wellness-Plan PRD contract using
the framework's generic format validators.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields for entities carrying id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("ESSENTIAL", "PLUS", "PREMIUM")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["annual_value_cents"], int) and data["annual_value_cents"] >= 0
    assert 0.0 <= data["alacarte_discount_pct"] <= 0.5
    assert isinstance(data["enrollment_fee_cents"], int) and data["enrollment_fee_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_plan_service(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert data["service_code"] in ("EXAM", "VACCINE", "DENTAL")
    assert isinstance(data["included_quantity"], int) and data["included_quantity"] >= 0
    assert isinstance(data["unit_value_cents"], int) and data["unit_value_cents"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_member_account(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data.get("home_clinic_id", "")), "home_clinic_id must be a valid UUID"
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_account_id", "")), "member_account_id must be a valid UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert isinstance(data["billing_anchor_day"], int)
    assert 1 <= data["billing_anchor_day"] <= 28
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["pet_count"], int) and data["pet_count"] >= 0
    assert isinstance(data["auto_renew"], bool)
    assert data["status"] in (
        "PENDING_PAYMENT", "ENROLLED", "SUSPENDED", "CANCEL_PENDING", "CANCELLED",
    )


def assert_enrolled_pet(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("membership_id", "")), "membership_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["species"] in ("DOG", "CAT")
    assert isinstance(data["weight_kg"], (int, float)) and data["weight_kg"] > 0
    assert is_iso8601_timestamp(data.get("enrolled_at", "")), "enrolled_at must be ISO 8601"
    assert data["status"] in ("ENROLLED", "SUSPENDED", "REMOVED")


def assert_contract_term(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("membership_id", "")), "membership_id must be a valid UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert isinstance(data["term_index"], int) and data["term_index"] >= 1
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert isinstance(data["entitlement_granted_cents"], int)
    assert isinstance(data["entitlement_consumed_cents"], int)
    assert isinstance(data["entitlement_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "RENEWAL_PENDING", "EXPIRED", "TERMINATED")


def assert_service_credit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_term_id", "")), "contract_term_id must be a valid UUID"
    assert data["service_code"] in ("EXAM", "VACCINE", "DENTAL")
    assert isinstance(data["granted_quantity"], int) and data["granted_quantity"] >= 0
    assert isinstance(data["consumed_quantity"], int) and data["consumed_quantity"] >= 0
    assert isinstance(data["unit_value_cents"], int)
    assert data["status"] in ("OPEN", "EXHAUSTED", "FORFEITED")


def assert_service_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("membership_id", "")), "membership_id must be a valid UUID"
    assert is_valid_uuid(data.get("enrolled_pet_id", "")), "enrolled_pet_id must be a valid UUID"
    assert is_valid_uuid(data.get("clinic_id", "")), "clinic_id must be a valid UUID"
    assert data["service_code"] in ("EXAM", "VACCINE", "DENTAL")
    assert is_iso8601_timestamp(data.get("visited_at", "")), "visited_at must be ISO 8601"
    assert isinstance(data["covered_by_credit"], bool)
    assert isinstance(data["charged_cents"], int) and data["charged_cents"] >= 0
    assert data["status"] in ("COMPLETED", "VOIDED")


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("membership_id", "")), "membership_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert isinstance(data["fee_charged_cents"], int)
    assert isinstance(data["proration_credit_cents"], int)
    assert data["status"] == "BILLED"


def assert_plan_change_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("membership_id", "")), "membership_id must be a valid UUID"
    assert is_valid_uuid(data.get("from_plan_id", "")), "from_plan_id must be a valid UUID"
    assert is_valid_uuid(data.get("to_plan_id", "")), "to_plan_id must be a valid UUID"
    assert data["change_kind"] in ("UPGRADE", "DOWNGRADE")
    assert isinstance(data["proration_delta_cents"], int)
    assert data["status"] in ("APPLIED", "SUPERSEDED")


def assert_term_balance_reconciled(term: dict):
    """Derived-balance invariant from PRD §3.7: balance == granted - consumed."""
    assert term["entitlement_balance_cents"] == (
        term["entitlement_granted_cents"] - term["entitlement_consumed_cents"]
    ), "entitlement_balance_cents must equal granted minus consumed"
