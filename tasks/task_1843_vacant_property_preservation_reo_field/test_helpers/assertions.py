"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_servicer(data: dict):
    _assert_common_fields(data, "Servicer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["active"], bool)
    assert isinstance(data["prior_month_gross_cents"], int)
    assert isinstance(data["volume_rebate_cents"], int)


def assert_crew(data: dict):
    _assert_common_fields(data, "Crew")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert isinstance(data["daily_capacity_jobs"], int) and data["daily_capacity_jobs"] >= 1


def assert_investor_allowable(data: dict):
    _assert_common_fields(data, "InvestorAllowable")
    assert data["investor_type"] in ["FHA", "FNMA", "FHLMC", "PRIVATE"]
    assert isinstance(data["max_per_occurrence_cents"], int)
    assert isinstance(data["max_occurrences_per_calendar_year"], int)
    assert isinstance(data["aggregate_cap_cents_per_property_year"], int)
    assert isinstance(data["requires_bid_over_cents"], int)


def assert_property(data: dict):
    _assert_common_fields(data, "Property")
    assert data["status"] in ["ACTIVE", "CONVEYED"]
    assert data["occupancy_status"] in ["UNKNOWN", "VACANT", "OCCUPIED_PENDING_VERIFICATION", "OCCUPIED"]
    assert data["compliance_posture"] in ["CLEAR", "AT_RISK", "NON_COMPLIANT"]
    assert isinstance(data["condition_score"], int) and 0 <= data["condition_score"] <= 100
    assert isinstance(data["ytd_investor_approved_cents"], int)
    assert isinstance(data["financial_review_required"], bool)


def assert_work_order(data: dict):
    _assert_common_fields(data, "WorkOrder")
    assert data["status"] in [
        "ISSUED", "ASSIGNED", "IN_PROGRESS", "SUBMITTED",
        "APPROVED", "COMPLETED", "CANCELLED", "EXPIRED",
    ]
    assert data["source"] in ["DIRECT", "BID_CONVERTED", "RECURRING_AUTO"]
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["allowable_cap_cents"], int)
    assert isinstance(data["requires_bid_over_cents"], int)
    assert isinstance(data["evidence_complete"], bool)


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED", "VERIFICATION_PENDING"]
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1


def assert_disposition(data: dict):
    _assert_common_fields(data, "PersonalPropertyDisposition")
    assert data["status"] in [
        "IN_HOLD", "RELEASE_ELIGIBLE", "DISPOSAL_AUTHORIZED",
        "DISPOSED", "DONATED", "RETURNED",
    ]
    assert isinstance(data["valuation_cents"], int)


def assert_recurring_plan(data: dict):
    _assert_common_fields(data, "RecurringServicePlan")
    assert data["status"] in ["ACTIVE", "SUSPENDED", "ENDED"]
    assert data["service_type"] in ["GRASS_CUT", "SNOW_REMOVAL"]
    assert isinstance(data["generated_this_season"], int) and data["generated_this_season"] >= 0


def assert_code_violation(data: dict):
    _assert_common_fields(data, "CodeViolation")
    assert data["status"] in ["OPEN", "CURE_IN_PROGRESS", "CURE_SUBMITTED", "VERIFIED_CLOSED", "ESCALATED"]
    assert data["violation_class"] in ["MINOR", "MAJOR", "HAZARDOUS"]
    assert isinstance(data["accrued_fine_cents"], int) and data["accrued_fine_cents"] >= 0


def assert_registration(data: dict):
    _assert_common_fields(data, "MunicipalRegistration")
    assert data["status"] in ["PENDING", "ACTIVE", "EXPIRED", "RELEASED"]
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_damage_report(data: dict):
    _assert_common_fields(data, "DamageReport")
    assert data["status"] in [
        "REPORTED", "TRIAGED", "BID_REQUESTED", "REPAIR_IN_PROGRESS",
        "MONITORING", "CLOSED",
    ]
    assert isinstance(data["is_interior"], bool)


def assert_bid(data: dict):
    _assert_common_fields(data, "Bid")
    assert data["status"] in ["DRAFT", "SUBMITTED", "COUNTERED", "APPROVED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1


def assert_photo_evidence(data: dict):
    _assert_common_fields(data, "PhotoEvidence")
    assert data["category"] in [
        "BEFORE", "DURING", "AFTER", "SERIAL_NUMBER",
        "DAMAGE_CLOSEUP", "STREET_SCENE", "DOCUMENT",
    ]
    assert isinstance(data["flagged"], bool)


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "PARTIALLY_APPROVED",
        "DENIED", "PAID", "VOIDED",
    ]
    assert isinstance(data["claimed_total_cents"], int)
    assert isinstance(data["appeal_round"], int) and 0 <= data["appeal_round"] <= 1


def assert_expense_line(data: dict):
    _assert_common_fields(data, "ExpenseLine")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["claimed_cents"], int)
    assert data["claimed_cents"] == data["quantity"] * data["unit_price_cents"], (
        "claimed_cents must equal quantity * unit_price_cents"
    )


def assert_property_invariants(data: dict):
    """Domain invariants that must hold for a property after any operation."""
    score = data["condition_score"]
    posture = data["compliance_posture"]
    expected = "CLEAR" if score >= 80 else ("AT_RISK" if score >= 50 else "NON_COMPLIANT")
    assert posture == expected, f"posture {posture} inconsistent with score {score}"
    assert data["ytd_investor_approved_cents"] >= 0
