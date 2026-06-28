"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_homeowner(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["state_code"], str)


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["homeowner_id"], str)
    assert isinstance(data["address_line"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["utility_territory_code"], str)
    assert isinstance(data["service_voltage"], int)
    assert data["main_breaker_amps"] in (100, 150, 200)
    assert isinstance(data["floor_area_sqft"], int) and data["floor_area_sqft"] > 0


def assert_electrician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_state_code"], str)
    assert isinstance(data["max_daily_jobs"], int) and data["max_daily_jobs"] > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_charger_product(data: dict):
    # common_fields: false — only id + created_at; no updated_at, no version.
    _assert_common(data, with_version=False)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert data["rated_amps"] in (32, 40, 48)
    assert data["required_circuit_amps"] in (40, 50, 60)
    assert isinstance(data["msrp_cents"], int) and data["msrp_cents"] >= 0


def assert_install_job(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["charger_product_sku"], str)
    assert data["workflow_status"] in (
        "CREATED", "ASSESSED", "QUOTED", "SCHEDULED",
        "INSTALLED", "ACTIVATED", "CLOSED", "CANCELLED",
    )
    assert data["compliance_status"] in (
        "PENDING_REVIEW", "PERMIT_PENDING", "CLEARED", "BLOCKED",
    )
    assert isinstance(data["requires_panel_upgrade"], bool)


def assert_site_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["install_job_id"], str)
    assert data["assessment_method"] in ("STANDARD_220_83", "LOAD_STUDY_220_87")
    assert isinstance(data["existing_demand_va"], int)
    assert isinstance(data["spare_capacity_va"], int)
    assert isinstance(data["charger_fits"], bool)
    assert data["status"] in ("DRAFT", "ACCEPTED", "SUPERSEDED")


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["install_job_id"], str)
    assert isinstance(data["labor_cents"], int) and data["labor_cents"] >= 0
    assert isinstance(data["parts_line_cents"], list)
    assert isinstance(data["base_subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["permit_fee_cents"], int)
    assert isinstance(data["quote_total_cents"], int)
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "REJECTED")


def assert_permit_application(data: dict):
    _assert_common(data)
    assert isinstance(data["install_job_id"], str)
    assert isinstance(data["jurisdiction_code"], str)
    assert data["status"] in ("SUBMITTED", "CORRECTIONS_REQUESTED", "APPROVED", "REJECTED")
    assert isinstance(data["correction_rounds"], int) and data["correction_rounds"] >= 0


def assert_interconnection_request(data: dict):
    _assert_common(data)
    assert isinstance(data["install_job_id"], str)
    assert isinstance(data["utility_territory_code"], str)
    assert isinstance(data["requested_load_amps"], int)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "APPROVED", "DENIED")


def assert_dispatch_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["install_job_id"], str)
    assert isinstance(data["electrician_id"], str)
    assert isinstance(data["window_start_minute"], int)
    assert isinstance(data["window_end_minute"], int)
    assert data["window_end_minute"] > data["window_start_minute"]
    assert data["status"] in ("BOOKED", "EN_ROUTE", "COMPLETED", "CANCELLED")


def assert_incentive_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["install_job_id"], str)
    assert data["program_kind"] in ("FEDERAL_45W", "UTILITY_REBATE")
    assert isinstance(data["eligible_cost_cents"], int) and data["eligible_cost_cents"] >= 0
    assert isinstance(data["award_cents"], int) and data["award_cents"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "REVERSED")


def assert_panel_upgrade_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["install_job_id"], str)
    assert data["recommended_main_amps"] in (150, 200)
    assert data["status"] in ("OPEN", "ACCEPTED", "DECLINED", "COMPLETED")


def assert_warranty_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["install_job_id"], str)
    assert isinstance(data["summary"], str)
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in ("OPEN", "DIAGNOSING", "AWAITING_PARTS", "RESOLVED", "CLOSED")
