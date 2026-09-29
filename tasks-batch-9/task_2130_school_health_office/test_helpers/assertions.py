"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COVERAGE_POSTURES = ["FULL", "LIMITED", "UNCOVERED"]
STOCK_STATUSES = ["READY", "DEGRADED", "DEPLETED"]
ALERT_FLAG_VALUES = [
    "ALLERGY_ANAPHYLAXIS", "IMMUNIZATION_HOLD", "NO_ACTIVE_PLAN",
    "SCREENING_REFERRAL", "SELF_CARRY",
]


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer starting at 1"


def assert_school(data: dict):
    _assert_common(data, "School")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["building_code"], str) and data["building_code"]
    assert isinstance(data["cot_capacity"], int)
    assert isinstance(data["emergency_protocol_enabled"], bool)
    for counter in ("enrolled_student_count", "eligible_stock_student_count",
                    "base_required_units", "surge_units", "required_stock_units",
                    "occupied_cot_count", "contracted_weekly_minutes"):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"School.{counter} must be a non-negative integer"
    assert data["coverage_posture"] in COVERAGE_POSTURES
    assert data["stock_protocol_status"] in STOCK_STATUSES
    assert isinstance(data["epinephrine_days_of_supply"], (int, float))
    assert isinstance(data["albuterol_days_of_supply"], (int, float))


def assert_nurse(data: dict):
    _assert_common(data, "Nurse")
    assert data["credential"] in ["RN", "LPN", "HEALTH_AIDE"]
    assert data["employment_status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["delegation_authorized"], bool)
    assert_nurse_minute_conservation(data)


def assert_nurse_minute_conservation(data: dict):
    """weekly_contracted_minutes always equals committed plus uncommitted."""
    assert data["weekly_contracted_minutes"] == data["committed_weekly_minutes"] + data["uncommitted_weekly_minutes"], (
        f"Nurse minute conservation broken: {data['weekly_contracted_minutes']} != "
        f"{data['committed_weekly_minutes']} + {data['uncommitted_weekly_minutes']}"
    )
    assert data["uncommitted_weekly_minutes"] >= 0, "uncommitted_weekly_minutes must never be negative"


def assert_coverage_assignment(data: dict):
    _assert_common(data, "CoverageAssignment")
    assert data["weekday"] in ["MON", "TUE", "WED", "THU", "FRI"]
    assert data["status"] in ["SCHEDULED", "ACTIVE", "ENDED"]
    assert data["duration_minutes"] == data["end_minute"] - data["start_minute"]


def assert_student(data: dict):
    _assert_common(data, "Student")
    assert data["enrollment_status"] in ["ENROLLED", "TRANSFERRED", "WITHDRAWN"]
    assert data["allergy_severity"] in ["NONE", "MILD", "MODERATE", "ANAPHYLAXIS"]
    assert data["immunization_status"] in ["COMPLIANT", "PROVISIONAL", "EXEMPT", "NONCOMPLIANT"]
    assert data["risk_tier"] in ["ROUTINE", "ELEVATED", "CRITICAL"]
    assert 0 <= data["intake_risk_score"] <= 100
    assert 0 <= data["observed_risk_score"] <= 100
    assert data["effective_risk_score"] == max(data["intake_risk_score"], data["observed_risk_score"])
    assert isinstance(data["alert_flags"], list)
    assert all(flag in ALERT_FLAG_VALUES for flag in data["alert_flags"]), \
        f"unexpected alert flag in {data['alert_flags']}"
    assert data["alert_flags"] == sorted(data["alert_flags"]), "alert_flags must be in ascending sorted order"


def assert_action_plan(data: dict):
    _assert_common(data, "ActionPlan")
    assert data["status"] in ["DRAFT", "PENDING_GUARDIAN", "PENDING_PROVIDER", "ACTIVE",
                              "SUPERSEDED", "EXPIRED", "REVOKED"]
    assert data["condition_code"] in ["ASTHMA", "ANAPHYLAXIS", "SEIZURE", "T1DM"]
    assert 1 <= data["severity_score"] <= 5
    assert 0 <= data["revision_round"] <= 2


def assert_medication_authorization(data: dict):
    _assert_common(data, "MedicationAuthorization")
    assert data["consent_status"] in ["CONSENT_PENDING", "CONSENT_GRANTED", "CONSENT_WITHDRAWN"]
    assert data["clinical_status"] in ["UNVERIFIED", "VERIFIED", "SUSPENDED", "EXPIRED"]
    assert isinstance(data["is_controlled"], bool)
    assert isinstance(data["dispensable"], bool)
    assert data["is_controlled"] == (data["medication_code"] == "METHYLPHENIDATE")


def assert_stock_lot(data: dict):
    _assert_common(data, "MedicationStockLot")
    assert data["status"] in ["AVAILABLE", "QUARANTINED", "DEPLETED", "EXPIRED"]
    assert_lot_unit_conservation(data)


def assert_lot_unit_conservation(data: dict):
    """received_total always equals on_hand + reserved + administered + wasted."""
    total = (data["quantity_on_hand"] + data["quantity_reserved"]
             + data["quantity_administered"] + data["quantity_wasted"])
    assert data["received_total"] == total, (
        f"Lot unit conservation broken: received_total={data['received_total']} but "
        f"on_hand={data['quantity_on_hand']} + reserved={data['quantity_reserved']} + "
        f"administered={data['quantity_administered']} + wasted={data['quantity_wasted']} = {total}"
    )
    assert data["quantity_available"] == data["quantity_on_hand"], \
        "quantity_available is an alias of quantity_on_hand"


def assert_health_visit(data: dict):
    _assert_common(data, "HealthVisit")
    assert data["status"] in ["OPEN", "IN_ASSESSMENT", "DISPOSITIONED", "CLOSED", "REOPENED"]
    assert data["acuity"] in ["ROUTINE", "URGENT", "EMERGENT"]
    assert data["complaint_code"] in ["INJURY", "ILLNESS", "MEDICATION", "CHRONIC_CARE",
                                      "MENTAL_HEALTH", "SCREENING_FOLLOWUP"]
    assert 0 <= data["triage_score"] <= 100
    assert data["requires_ems_review"] == (data["triage_score"] >= 85)
    assert is_iso8601_timestamp(data["arrival_at"])


def assert_administration_record(data: dict):
    _assert_common(data, "AdministrationRecord")
    assert data["status"] in ["PREPARED", "ADMINISTERED", "REFUSED", "WASTED", "VOIDED"]
    assert data["protocol_mode"] in ["AUTHORIZED", "STOCK_EMERGENCY"]
    assert 1 <= data["units"] <= 10
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must name the selected lot"


def assert_screening(data: dict):
    _assert_common(data, "Screening")
    assert data["status"] in ["SCHEDULED", "COMPLETED", "RESCREEN_DUE", "REFERRED", "CLOSED", "DECLINED"]
    assert data["screening_type"] in ["VISION", "HEARING", "SCOLIOSIS"]
    assert data["outcome"] in [None, "PASS", "REFER", "INCONCLUSIVE"]
    assert 1 <= data["cycle_number"] <= 3


def assert_disclosure_request(data: dict):
    _assert_common(data, "DisclosureRequest")
    assert data["status"] in ["DRAFT", "CONSENT_PENDING", "AWAITING_DECISION", "APPROVED",
                              "DENIED", "RELEASED", "EXPIRED", "REVOKED"]
    assert data["redaction_level"] in ["NONE", "PARTIAL", "FULL"]
    assert data["requester_type"] in ["GUARDIAN", "EXTERNAL_PROVIDER", "SCHOOL_STAFF", "AGENCY"]
    assert isinstance(data["scope"], list) and len(data["scope"]) > 0
    assert isinstance(data["release_package_item_count"], int)
