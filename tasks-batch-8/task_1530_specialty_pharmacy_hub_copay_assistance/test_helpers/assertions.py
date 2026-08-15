"""Entity assertions and domain invariant checkers (PRD sections 2-3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_drug_program(data: dict):
    _assert_common_fields(data, "DrugProgram")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["manufacturer_name"], str) and data["manufacturer_name"]
    assert isinstance(data["diagnosis_code"], str) and data["diagnosis_code"]
    assert isinstance(data["requires_injection_training"], bool)
    assert isinstance(data["requires_cold_chain"], bool)
    assert isinstance(data["max_transit_hours"], int)
    assert isinstance(data["min_days_between_fills"], int)
    assert isinstance(data["copay_card_per_fill_cap_cents"], int)
    assert isinstance(data["copay_card_annual_cap_cents"], int)
    assert isinstance(data["default_days_supply"], int)


def assert_foundation_pool(data: dict):
    _assert_common_fields(data, "FoundationPool")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["diagnosis_code"], str) and data["diagnosis_code"]
    assert isinstance(data["total_funding_cents"], int)
    assert isinstance(data["grant_amount_cents"], int)
    assert isinstance(data["coverage_pct"], int)
    assert 0 <= data["coverage_pct"] <= 100
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["remaining_balance_cents"], int)


def assert_enrollment(data: dict):
    _assert_common_fields(data, "Enrollment")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert isinstance(data["diagnosis_code"], str) and data["diagnosis_code"]
    assert isinstance(data["case_manager_id"], str) and data["case_manager_id"]
    assert data["status"] in [
        "INTAKE", "BENEFITS_VERIFIED", "PA_PENDING", "PA_DENIED",
        "APPROVED", "ACTIVE", "DENIED_CLOSED", "DISCONTINUED",
    ]
    assert isinstance(data["training_sessions_completed"], int)
    assert isinstance(data["fills_delivered_count"], int)
    assert data.get("therapy_start_date") is None or \
        isinstance(data["therapy_start_date"], str)
    assert isinstance(data["payer_accumulated_oop_cents"], int)
    assert data.get("remaining_oop_cents") is None or \
        isinstance(data["remaining_oop_cents"], int)
    assert data.get("pdc_confirmed_pct") is None or \
        isinstance(data["pdc_confirmed_pct"], (int, float))
    assert data.get("pdc_provisional_pct") is None or \
        isinstance(data["pdc_provisional_pct"], (int, float))


def assert_benefits_investigation(data: dict):
    """Immutable record: id + created_at, and no updated_at/version keys
    (PRD 2.4: both updated_at and version are absent from it)."""
    assert is_valid_uuid(data.get("id", "")), \
        "BenefitsInvestigation.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "BenefitsInvestigation.created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "BenefitsInvestigation must not carry updated_at"
    assert "version" not in data, \
        "BenefitsInvestigation must not carry version"
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["requires_prior_auth"], bool)
    assert isinstance(data["plan_has_accumulator"], bool)
    assert isinstance(data["patient_cost_share_cents"], int)
    assert isinstance(data["oop_max_cents"], int)


def assert_prior_authorization(data: dict):
    _assert_common_fields(data, "PriorAuthorization")
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert isinstance(data["clinical_notes"], str)
    assert isinstance(data["payer_reference"], str)
    assert data["status"] in [
        "SUBMITTED", "APPEALED", "APPROVED", "DENIED", "DENIED_FINAL",
    ]
    assert isinstance(data["appeal_round"], int)
    assert data.get("decision_rationale") is None or \
        isinstance(data["decision_rationale"], str)


def assert_copay_assistance(data: dict):
    _assert_common_fields(data, "CopayAssistance")
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert data["assistance_type"] in ["COPAY_CARD", "FOUNDATION"]
    assert data.get("foundation_pool_id") is None or \
        isinstance(data["foundation_pool_id"], str)
    assert isinstance(data["matched_by_user_id"], str)
    assert data["status"] in ["RESERVED", "ACTIVE", "EXHAUSTED", "RELEASED"]
    assert data.get("per_fill_cap_cents") is None or \
        isinstance(data["per_fill_cap_cents"], int)
    assert data.get("coverage_pct") is None or \
        isinstance(data["coverage_pct"], int)
    assert isinstance(data["annual_benefit_cap_cents"], int)
    assert isinstance(data["remaining_annual_benefit_cents"], int)
    assert isinstance(data["disbursed_cents"], int)


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert isinstance(data["fill_number"], int)
    assert data["fill_type"] in ["FIRST_FILL", "REFILL"]
    assert isinstance(data["requested_delivery_date"], str)
    assert isinstance(data["transit_hours"], int)
    assert isinstance(data["days_supply"], int)
    assert data["status"] in [
        "REQUESTED", "SCHEDULED", "SHIPPED", "DELIVERED", "SPOILED", "CANCELLED",
    ]
    assert isinstance(data["patient_cost_share_cents"], int)
    assert data.get("assistance_pay_cents") is None or \
        isinstance(data["assistance_pay_cents"], int)
    assert data.get("patient_pay_cents") is None or \
        isinstance(data["patient_pay_cents"], int)
    assert data.get("payer_accumulator_delta_cents") is None or \
        isinstance(data["payer_accumulator_delta_cents"], int)
    assert data.get("delivered_date") is None or \
        isinstance(data["delivered_date"], str)


def assert_nurse_visit(data: dict):
    _assert_common_fields(data, "NurseVisit")
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert isinstance(data["nurse_id"], str) and data["nurse_id"]
    assert is_iso8601_timestamp(data.get("window_start", "")), \
        "NurseVisit.window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), \
        "NurseVisit.window_end must be ISO 8601"
    assert data["status"] in ["SCHEDULED", "COMPLETED", "NO_SHOW"]
    assert data.get("completed_by_user_id") is None or \
        isinstance(data["completed_by_user_id"], str)


def assert_adverse_event(data: dict):
    _assert_common_fields(data, "AdverseEvent")
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert is_iso8601_timestamp(data.get("awareness_at", "")), \
        "AdverseEvent.awareness_at must be ISO 8601"
    assert data["seriousness"] in ["SERIOUS", "NON_SERIOUS"]
    assert isinstance(data["description"], str)
    assert isinstance(data["reported_by_user_id"], str)
    assert data["status"] in ["REPORTED", "ACKNOWLEDGED"]


def assert_outcome_report(data: dict):
    _assert_common_fields(data, "OutcomeReport")
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["created_by_user_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "SUPERSEDED"]
    assert isinstance(data["fills_delivered_count"], int)
    assert isinstance(data["adverse_event_count"], int)
    assert isinstance(data["total_assistance_cents"], int)
    assert data.get("pdc_pct") is None or isinstance(data["pdc_pct"], (int, float))


def assert_oop_partition(enrollment: dict, oop_max_cents: int):
    """Payer OOP partition identity: accumulated + remaining == oop_max."""
    acc = enrollment["payer_accumulated_oop_cents"]
    rem = enrollment["remaining_oop_cents"]
    assert rem is not None, "remaining_oop_cents must be set once a BI exists"
    assert acc + rem == oop_max_cents, (
        f"OOP partition broken: {acc} + {rem} != {oop_max_cents}"
    )
