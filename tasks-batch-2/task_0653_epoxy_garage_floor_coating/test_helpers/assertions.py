"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape and field domains the PRD declares.
Use the framework's generic UUID / timestamp checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_coating_system(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["family"] in ("FLAKE", "METALLIC")
    assert data["sku"] in ("FLAKE_STANDARD", "FLAKE_PREMIUM", "METALLIC")
    assert isinstance(data["requires_metallic_certified_crew"], bool)
    assert isinstance(data["active"], bool)


def assert_color_option(data: dict):
    _common(data)
    assert is_valid_uuid(data["coating_system_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["flake_blend_code"], str)
    assert isinstance(data["active"], bool)


def assert_financing_plan(data: dict):
    _common(data)
    assert isinstance(data["apr_bps"], int) and 0 <= data["apr_bps"] <= 3500
    assert isinstance(data["term_months"], int) and 1 <= data["term_months"] <= 84
    assert isinstance(data["min_principal_cents"], int) and data["min_principal_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_crew(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["metallic_certified"], bool)
    assert isinstance(data["max_sqft_per_day"], int) and data["max_sqft_per_day"] >= 1
    assert isinstance(data["active"], bool)


def assert_customer(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["referral_code"], str) and data["referral_code"]
    assert isinstance(data["account_credit_balance_cents"], int)
    assert data["account_credit_balance_cents"] >= 0


def assert_project(data: dict):
    _common(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["site_zip"], str)
    assert data["sales_status"] in ("LEAD", "ASSESSED", "QUOTED", "ACCEPTED", "DECLINED")
    assert data["build_status"] in (
        "PRE_BUILD", "SCHEDULED", "INSTALLED", "CURING", "COMPLETE", "CANCELLED"
    )


def assert_assessment(data: dict):
    _common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["measured_sqft"], int) and data["measured_sqft"] >= 1
    assert 0 <= data["oil_stain_pct"] <= 100
    assert 0 <= data["moisture_pct"] <= 100
    assert isinstance(data["condition_score"], int) and 0 <= data["condition_score"] <= 100
    assert data["prep_tier"] in ("LIGHT", "MODERATE", "HEAVY")
    assert isinstance(data["billable_crack_ft"], int) and data["billable_crack_ft"] >= 0
    assert data["status"] in ("APPROVED", "SUPERSEDED")


def assert_quote(data: dict):
    _common(data)
    assert is_valid_uuid(data["project_id"])
    assert data["variant"] in ("ESTIMATE", "FINAL")
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "DECLINED", "SUPERSEDED")
    assert isinstance(data["priced_sqft"], int) and data["priced_sqft"] >= 0
    for f in ("system_material_cents", "prep_labor_cents", "discount_cents",
              "mobilization_cents", "grand_total_cents", "monthly_payment_cents",
              "volume_discount_pct_bps"):
        assert isinstance(data[f], int), f"{f} must be integer cents/bps"
    assert data["grand_total_cents"] >= 0


def assert_install_job(data: dict):
    _common(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["crew_id"])
    assert is_iso8601_timestamp(data["install_date"])
    assert is_iso8601_timestamp(data["install_end"])
    assert is_iso8601_timestamp(data["foot_traffic_ok_at"])
    assert is_iso8601_timestamp(data["vehicle_traffic_ok_at"])
    assert data["status"] in ("BOOKED", "IN_PROGRESS", "COMPLETED", "CURED", "CANCELLED")


def assert_warranty(data: dict):
    _common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["covered_install_price_cents"], int)
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    assert is_iso8601_timestamp(data["coverage_start_at"])
    assert data["status"] in ("ACTIVE", "CLAIM_OPEN", "VOID")


def assert_warranty_claim(data: dict):
    _common(data)
    assert is_valid_uuid(data["warranty_id"])
    assert data["defect_type"] in ("HOT_TIRE", "PEEL", "OTHER")
    assert isinstance(data["months_elapsed"], int) and data["months_elapsed"] >= 0
    assert isinstance(data["prorated_credit_cents"], int) and data["prorated_credit_cents"] >= 0
    assert isinstance(data["revision_rounds"], int) and data["revision_rounds"] >= 0
    assert data["status"] in (
        "SUBMITTED", "NEEDS_INFO", "APPROVED", "REJECTED", "CALLBACK_SCHEDULED", "CLOSED"
    )


def assert_referral(data: dict):
    _common(data)
    assert is_valid_uuid(data["referrer_customer_id"])
    assert is_valid_uuid(data["referred_customer_id"])
    assert isinstance(data["credit_cents"], int)
    assert data["status"] in ("PENDING", "CONVERTED", "CLAWED_BACK", "EXPIRED")
