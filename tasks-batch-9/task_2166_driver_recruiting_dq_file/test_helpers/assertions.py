"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ANNUAL_REVIEW_DENOMINATOR,
    DOC_WEIGHTS,
    LOOKBACK_DAYS,
    PRE_HIRE_DENOMINATOR,
    TOTAL_DOC_WEIGHT,
)

_DATE_LEN = 10


def _assert_common_fields(data: dict, label: str) -> None:
    """Every entity carries id, created_at, updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_calendar_date(value, label: str) -> None:
    assert isinstance(value, str) and len(value) == _DATE_LEN and value[4] == "-" and value[7] == "-", (
        f"{label} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_carrier(data: dict) -> None:
    _assert_common_fields(data, "Carrier")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["dot_number"], str) and 1 <= len(data["dot_number"]) <= 12
    assert data["safety_rating"] in ("SATISFACTORY", "CONDITIONAL", "UNSATISFACTORY")
    assert isinstance(data["open_requisitions"], int) and data["open_requisitions"] >= 0
    assert isinstance(data["filled_requisitions"], int) and data["filled_requisitions"] >= 0
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["deficiency_ratio"], (int, float))
    assert round(float(data["deficiency_ratio"]), 4) == pytest.approx(
        float(data["deficiency_ratio"])
    ), "deficiency_ratio carries at most 4 decimal places"


def assert_driver_applicant(data: dict) -> None:
    _assert_common_fields(data, "DriverApplicant")
    assert is_valid_uuid(data["carrier_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_calendar_date(data["date_of_birth"], "DriverApplicant.date_of_birth")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["cdl_number"], str)
    assert isinstance(data["cdl_state"], str) and len(data["cdl_state"]) == 2
    assert data["cdl_class"] in ("CLASS_A", "CLASS_B", "CLASS_C")
    assert isinstance(data["experience_months"], int) and data["experience_months"] >= 0
    assert data["cdl_downgrade_risk"] in (
        "NO_CERTIFICATE", "NONE", "WATCH", "IMMINENT", "EXPIRED_GRACE", "DOWNGRADED",
    )
    assert data["rehire_eligibility"] in (
        "ELIGIBLE", "COOLDOWN", "PERMANENTLY_INELIGIBLE",
    )
    assert isinstance(data["outstanding_clawback_cents"], int)


def assert_driver_application(data: dict) -> None:
    _assert_common_fields(data, "DriverApplication")
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert data["position_type"] in ("OTR", "REGIONAL", "LOCAL")
    assert data["screening_status"] in (
        "DRAFT", "SUBMITTED", "SCREENING", "INFO_REQUESTED", "SCREEN_CLEARED", "SCREEN_FAILED",
    )
    assert data["qualification_status"] in (
        "NOT_STARTED", "IN_PROGRESS", "ROAD_TEST_PASSED", "ORIENTATION_COMPLETE",
        "QUALIFIED", "HIRED", "DISQUALIFIED",
    )
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 3
    assert isinstance(data["verified_coverage_days"], int)
    assert isinstance(data["gap_days_unexplained"], int)
    assert_coverage_identity(data["verified_coverage_days"], data["gap_days_unexplained"])


def assert_employment_verification(data: dict) -> None:
    _assert_common_fields(data, "EmploymentVerification")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["employer_name"], str) and data["employer_name"]
    assert isinstance(data["is_dot_regulated"], bool)
    assert_calendar_date(data["employed_from"], "EmploymentVerification.employed_from")
    assert_calendar_date(data["employed_to"], "EmploymentVerification.employed_to")
    assert data["employed_to"] > data["employed_from"], (
        "employed_to must fall strictly after employed_from"
    )
    assert data["status"] in (
        "PENDING", "REQUESTED", "NO_RESPONSE", "RESPONDED_VERIFIED",
        "RESPONDED_DISPUTED", "GOOD_FAITH_DOCUMENTED",
    )
    assert isinstance(data["request_round"], int) and data["request_round"] >= 0


def assert_screening_check(data: dict) -> None:
    _assert_common_fields(data, "ScreeningCheck")
    assert is_valid_uuid(data["application_id"])
    assert data["check_type"] in ("MVR", "PSP", "CRIMINAL")
    assert data["status"] in (
        "ORDERED", "RECEIVED", "PRE_ADVERSE", "DISPUTED", "ADJUDICATED_PASS", "ADVERSE_FINAL",
    )
    for count_field in ("violation_points", "serious_violation_count", "crash_preventable_count"):
        if data.get(count_field) is not None:
            assert isinstance(data[count_field], int), f"{count_field} must be an integer"
    if data.get("adjudication_score") is not None:
        assert isinstance(data["adjudication_score"], (int, float))
        assert round(float(data["adjudication_score"]), 2) == pytest.approx(
            float(data["adjudication_score"])
        ), "adjudication_score carries at most 2 decimal places"
    if data["check_type"] != "MVR":
        assert data.get("expires_on") is None, "only an MVR check carries an expires_on"


def assert_clearinghouse_query(data: dict) -> None:
    _assert_common_fields(data, "ClearinghouseQuery")
    assert is_valid_uuid(data["application_id"])
    assert data["query_type"] in ("LIMITED", "FULL")
    assert data["status"] in (
        "CONSENT_PENDING", "CONSENT_GRANTED", "CONSENT_DENIED",
        "RESULT_CLEAR", "RESULT_INFO_EXISTS", "RESULT_PROHIBITED",
    )
    assert data["result"] in ("PENDING", "NO_INFO", "INFORMATION_EXISTS", "PROHIBITED")


def assert_drug_test_order(data: dict) -> None:
    _assert_common_fields(data, "DrugTestOrder")
    assert is_valid_uuid(data["application_id"])
    assert data["test_type"] in ("PRE_EMPLOYMENT", "RETURN_TO_DUTY")
    assert data["status"] in (
        "ORDERED", "COLLECTED", "LAB_NEGATIVE", "LAB_POSITIVE", "LAB_DILUTE",
        "MRO_VERIFIED_NEGATIVE", "MRO_VERIFIED_POSITIVE",
    )
    assert isinstance(data["dilute_recollect_count"], int)
    assert 0 <= data["dilute_recollect_count"] <= 1


def assert_road_test(data: dict) -> None:
    _assert_common_fields(data, "RoadTest")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["examiner_user_id"], str) and data["examiner_user_id"]
    assert data["vehicle_class"] in ("CLASS_A", "CLASS_B", "CLASS_C")
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "NO_SHOW")
    assert isinstance(data["attempt_number"], int) and 1 <= data["attempt_number"] <= 3
    for field in ("score_pretrip", "score_skills", "score_road"):
        value = data.get(field)
        if value is not None:
            assert isinstance(value, int) and 0 <= value <= 100, (
                f"{field} must be an integer between 0 and 100 inclusive"
            )
    if data.get("composite_score") is not None:
        assert round(float(data["composite_score"]), 1) == pytest.approx(
            float(data["composite_score"])
        ), "composite_score carries exactly one decimal place"


def assert_orientation_session(data: dict) -> None:
    _assert_common_fields(data, "OrientationSession")
    assert is_valid_uuid(data["carrier_id"])
    assert data["ends_at"] > data["starts_at"], "ends_at must fall strictly after starts_at"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["enrolled_count"] <= data["capacity"]
    assert data["status"] in ("PLANNED", "OPEN", "COMPLETED")


def assert_orientation_enrollment(data: dict) -> None:
    _assert_common_fields(data, "OrientationEnrollment")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ("RESERVED", "ATTENDED", "ABSENT", "CANCELLED")


def assert_dq_file(data: dict) -> None:
    _assert_common_fields(data, "DqFile")
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ("OPEN", "COMPLETE", "DEFICIENT", "ARCHIVED")
    assert data["review_state"] in ("NOT_DUE", "DUE", "OVERDUE")
    assert data["total_weight"] == TOTAL_DOC_WEIGHT, (
        "the twelve document weights always sum to 33"
    )
    assert 0.0 <= float(data["completeness_pct"]) <= 100.0
    assert round(float(data["completeness_pct"]), 2) == pytest.approx(
        float(data["completeness_pct"])
    ), "completeness_pct carries at most 2 decimal places"
    assert isinstance(data["deficiency_count"], int) and data["deficiency_count"] >= 0
    assert_calendar_date(data["opened_on"], "DqFile.opened_on")
    assert_calendar_date(data["next_review_due_on"], "DqFile.next_review_due_on")


def assert_dq_document(data: dict) -> None:
    _assert_common_fields(data, "DqDocument")
    assert is_valid_uuid(data["dq_file_id"])
    assert data["doc_type"] in DOC_WEIGHTS
    assert data["weight"] == DOC_WEIGHTS[data["doc_type"]], (
        f"{data['doc_type']} weighs {DOC_WEIGHTS[data['doc_type']]}"
    )
    assert data["status"] in ("MISSING", "PRESENT", "EXPIRED", "WAIVED")


def assert_tuition_agreement(data: dict) -> None:
    _assert_common_fields(data, "TuitionAgreement")
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["school_name"], str) and data["school_name"]
    assert isinstance(data["tuition_total_cents"], int) and data["tuition_total_cents"] >= 1
    assert isinstance(data["commitment_months"], int) and data["commitment_months"] >= 1
    assert data["status"] in ("PENDING", "ACTIVE", "FULFILLED", "TERMINATED_CLAWBACK")
    for field in (
        "base_monthly_cents", "monthly_reimbursement_cents", "forgiven_cents",
        "months_served", "reimbursed_cents", "bonus_paid_cents", "clawback_cents",
        "outstanding_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_hire_record(data: dict) -> None:
    _assert_common_fields(data, "HireRecord")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert_calendar_date(data["hired_on"], "HireRecord.hired_on")
    assert data["status"] in ("ACTIVE", "TERMINATED", "RESCINDED")
    assert data["termination_type"] in (
        "NONE", "VOLUNTARY", "INVOLUNTARY_PERFORMANCE", "INVOLUNTARY_SAFETY", "ABANDONMENT",
    )
    assert data["rehire_flag"] in ("ELIGIBLE", "NOT_ELIGIBLE", "CONDITIONAL")
    assert isinstance(data["tenure_days"], int) and data["tenure_days"] >= 0


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_tuition_cents_identity(agreement: dict) -> None:
    """PRD §3.9: tuition_total_cents == reimbursed + clawback + outstanding + forgiven.

    bonus_paid_cents sits deliberately outside the identity.
    """
    total = (
        agreement["reimbursed_cents"]
        + agreement["clawback_cents"]
        + agreement["outstanding_cents"]
        + agreement["forgiven_cents"]
    )
    assert total == agreement["tuition_total_cents"], (
        "tuition cents identity broken: "
        f"{agreement['reimbursed_cents']} + {agreement['clawback_cents']} + "
        f"{agreement['outstanding_cents']} + {agreement['forgiven_cents']} "
        f"!= {agreement['tuition_total_cents']}"
    )


def assert_coverage_identity(verified_coverage_days: int, gap_days_unexplained: int) -> None:
    """PRD §3.3: gap_days_unexplained is 1,095 minus the covered days."""
    assert verified_coverage_days + gap_days_unexplained == LOOKBACK_DAYS, (
        f"coverage identity broken: {verified_coverage_days} + {gap_days_unexplained} "
        f"!= {LOOKBACK_DAYS}"
    )


def assert_completeness_payload(payload: dict, variant: str) -> None:
    """Structural checks on the on-demand completeness read (PRD §3.7)."""
    assert payload["variant"] == variant
    expected_denominator = (
        PRE_HIRE_DENOMINATOR if variant == "pre_hire_provisional" else ANNUAL_REVIEW_DENOMINATOR
    )
    assert payload["denominator_weight"] == expected_denominator, (
        f"the {variant} accounting has a denominator of {expected_denominator}"
    )
    assert isinstance(payload["missing_doc_types"], list)
    assert payload["satisfied_weight"] <= payload["denominator_weight"]


def assert_carrier_seat_identity(carrier: dict, expected_free_seats: int) -> None:
    """open_requisitions - filled_requisitions is the conserved seat count."""
    free = carrier["open_requisitions"] - carrier["filled_requisitions"]
    assert free == expected_free_seats, (
        f"expected {expected_free_seats} free requisition seats, got {free}"
    )
