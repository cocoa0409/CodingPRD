"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity_label: str):
    """Common identity contract of PRD §2.5."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_housing_site(data: dict):
    _assert_common(data, "HousingSite")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in ["DRAFT", "OPENING", "OPEN", "CLOSING", "CLOSED"]
    assert data["compliance_posture"] in ["NORMAL", "WATCH", "RESTRICTED"]


def assert_season_window(data: dict):
    _assert_common(data, "SeasonWindow")
    assert isinstance(data["site_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["planned_open_date"], str)
    assert isinstance(data["planned_close_date"], str)
    assert data["status"] in ["PLANNED", "ACTIVE", "COMPLETED", "SUPERSEDED", "CANCELLED"]


def assert_building(data: dict):
    _assert_common(data, "Building")
    assert isinstance(data["site_id"], str)
    assert isinstance(data["name"], str)


def assert_housing_unit(data: dict):
    _assert_common(data, "HousingUnit")
    assert isinstance(data["building_id"], str)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["unit_code"], str)
    assert data["unit_type"] in ["FAMILY_UNIT", "SEASONAL_DORM"]
    assert isinstance(data["max_occupancy"], int) and data["max_occupancy"] >= 1
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] >= 0
    assert data["status"] in ["REGISTERED", "CERTIFIED", "OCCUPIED",
                              "HABITABILITY_HOLD", "CONDEMNED", "DECOMMISSIONED"]
    assert isinstance(data["current_occupancy"], int) and data["current_occupancy"] >= 0
    assert data["current_occupancy"] <= data["max_occupancy"]
    assert isinstance(data["habitability_score_cumulative"], (int, float))
    assert isinstance(data["habitability_score_worst_case"], (int, float))
    assert isinstance(data["under_pest_exclusion"], bool)


def assert_unit_certification(data: dict):
    _assert_common(data, "UnitCertification")
    assert isinstance(data["unit_id"], str)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "PASSED",
                              "FAILED", "VOIDED", "EXPIRED"]


def assert_household(data: dict):
    _assert_common(data, "Household")
    assert isinstance(data["head_of_household_name"], str)
    assert isinstance(data["annual_family_income_cents"], int)
    assert data["annual_family_income_cents"] >= 0
    assert isinstance(data["ag_work_verified"], bool)
    assert data["eligibility_status"] in ["PENDING_ELIGIBILITY", "ELIGIBLE", "INELIGIBLE"]
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    assert isinstance(data["minor_count"], int) and data["minor_count"] >= 0
    assert data["minor_count"] <= data["member_count"]
    assert isinstance(data["rehousing_priority"], bool)


def assert_household_member(data: dict):
    _assert_common(data, "HouseholdMember")
    assert isinstance(data["household_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert data["relationship"] in ["HEAD", "SPOUSE", "CHILD", "OTHER"]
    assert isinstance(data["is_minor"], bool)


def assert_tenancy(data: dict):
    _assert_common(data, "Tenancy")
    assert isinstance(data["household_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["move_in_date"], str)
    assert data["status"] in ["PENDING_MOVE_IN", "ACTIVE", "NOTICE",
                              "TERMINATED", "CANCELLED"]
    assert data.get("notice_reason") in [None, "RESIDENT", "OPERATOR", "CONDEMNATION"]
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["rent_bucket_balance_cents"], int)
    assert isinstance(data["utility_bucket_balance_cents"], int)
    assert isinstance(data["damage_bucket_balance_cents"], int)
    assert isinstance(data["is_delinquent"], bool)
    assert isinstance(data["subsidy_tier_percent"], (int, float))


def assert_charge_ledger_entry(data: dict):
    _assert_common(data, "ChargeLedgerEntry")
    assert isinstance(data["tenancy_id"], str)
    assert data["entry_type"] in ["RENT", "UTILITY_OVERAGE", "DAMAGE",
                                  "SUBSIDY_CREDIT", "PAYMENT"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["POSTED", "VOIDED"]
    assert isinstance(data["charge_date"], str)


def assert_deduction_authorization(data: dict):
    _assert_common(data, "DeductionAuthorization")
    assert isinstance(data["household_id"], str)
    assert 0 < data["cap_percent"] <= 1
    assert data["purpose"] in ["RENT", "RENT_AND_UTILITIES"]
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "REVOKED"]


def assert_work_order(data: dict):
    _assert_common(data, "WorkOrder")
    assert isinstance(data["unit_id"], str)
    assert data["category"] in ["PLUMBING", "ELECTRICAL", "STRUCTURAL",
                                "PEST", "APPLIANCE", "OTHER"]
    assert data["severity"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert data["status"] in ["REPORTED", "TRIAGED", "ASSIGNED", "IN_PROGRESS",
                              "COMPLETED", "VERIFIED", "REOPENED", "CLOSED",
                              "CANCELLED"]


def assert_pest_treatment(data: dict):
    _assert_common(data, "PestTreatment")
    assert isinstance(data["unit_id"], str)
    assert data["treatment_type"] in ["ROUTINE", "TARGETED", "FUMIGATION"]
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["reentry_buffer_days"], int)
    assert data["reentry_buffer_days"] >= 0
    assert data["status"] in ["SCHEDULED", "APPLIED", "CLEARED", "CANCELLED"]


def assert_complaint(data: dict):
    _assert_common(data, "Complaint")
    assert isinstance(data["tenancy_id"], str)
    assert data["category"] in ["HABITABILITY", "RENT", "UTILITY", "HARASSMENT", "OTHER"]
    assert data["status"] in ["FILED", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED",
                              "ESCALATED_TO_AGENCY", "CLOSED"]
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["sla_breached"], bool)


def assert_regulatory_inspection(data: dict):
    _assert_common(data, "RegulatoryInspection")
    assert isinstance(data["site_id"], str)
    assert data["agency"] in ["STATE_HOUSING", "USDA_RD", "HUD", "COUNTY_HEALTH"]
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in ["SCHEDULED", "CONDUCTED", "FINDINGS_ISSUED",
                              "CURE_CERTIFIED", "CLOSED", "CANCELLED"]
    assert isinstance(data["open_critical_count"], int)


def assert_service_referral(data: dict):
    _assert_common(data, "ServiceReferral")
    assert isinstance(data["household_id"], str)
    assert data["referral_type"] in ["EDUCATION", "HEALTH"]
    assert isinstance(data["agency_name"], str)
    assert data["status"] in ["INITIATED", "ACCEPTED_BY_AGENCY", "COMPLETED", "DECLINED"]


def assert_tenancy_invariants(tenancy: dict):
    """Ledger bucket invariants (PRD §3.5): the total is the sum of buckets."""
    total = (tenancy["rent_bucket_balance_cents"]
             + tenancy["utility_bucket_balance_cents"]
             + tenancy["damage_bucket_balance_cents"])
    assert tenancy["balance_cents"] == total, (
        f"balance_cents {tenancy['balance_cents']} != bucket sum {total}"
    )
    if tenancy["balance_cents"] == 0:
        assert tenancy["is_delinquent"] is False


def assert_statement_invariants(statement: dict):
    """Same invariants read through the computed statement endpoint."""
    total = (statement["rent_bucket_balance_cents"]
             + statement["utility_bucket_balance_cents"]
             + statement["damage_bucket_balance_cents"])
    assert statement["balance_cents"] == total, (
        f"statement balance_cents {statement['balance_cents']} != bucket sum {total}"
    )
    if statement["balance_cents"] == 0:
        assert statement["is_delinquent"] is False
        assert statement["oldest_unpaid_charge_date"] is None
