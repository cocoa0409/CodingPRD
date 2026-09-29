"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AbsenceStatus,
    AppealOutcome,
    AppealStatus,
    AssessmentStatus,
    CaseDecision,
    ConfidentialityPosture,
    DenialStatus,
    DocRequestStatus,
    EmploymentStatus,
    EssentialFunctionStatus,
    FunctionAnalysisStatus,
    HardshipVerdict,
    JobProfileStatus,
    OptionStatus,
    RequestStage,
    ScoringMode,
    TrialOutcome,
    TrialStatus,
)


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity: str = "resource"):
    """id, created_at, updated_at and version on a full-property entity."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert "_" not in str(data.get("id", "")), f"{entity}.id must carry no type prefix"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_journal_fields(data: dict, entity: str = "journal row"):
    """An append-only row carries id and created_at and neither of the other two."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_three_fraction_digits(timestamp: str, label: str = "timestamp"):
    assert isinstance(timestamp, str) and timestamp.endswith("Z"), (
        f"{label} must be a UTC ISO 8601 instant ending in Z, got {timestamp!r}"
    )
    assert "." in timestamp, f"{label} must carry fractional seconds: {timestamp!r}"
    fraction = timestamp.split(".")[-1].rstrip("Z")
    assert len(fraction) == 3 and fraction.isdigit(), (
        f"{label} must carry exactly three fractional-second digits: {timestamp!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_employee(data: dict):
    assert_common_fields(data, "Employee")
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["department_code"], str)
    assert isinstance(data["job_title"], str)
    assert isinstance(data["hire_date"], str)
    assert is_valid_uuid(data["job_profile_id"])
    assert isinstance(data["is_people_manager"], bool)
    assert isinstance(data["annual_salary_cents"], int) and data["annual_salary_cents"] >= 0
    assert data["employment_status"] in _values(EmploymentStatus)
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert isinstance(data["lifetime_denial_count"], int)
    assert data["lifetime_denial_count"] >= 0


def assert_job_profile(data: dict):
    assert_common_fields(data, "JobProfile")
    assert isinstance(data["job_code"], str) and data["job_code"]
    assert isinstance(data["title"], str)
    assert isinstance(data["department_code"], str)
    assert isinstance(data["department_annual_budget_cents"], int)
    assert data["department_annual_budget_cents"] > 0
    assert isinstance(data["employer_annual_budget_cents"], int)
    assert data["employer_annual_budget_cents"] > 0
    assert data["status"] in _values(JobProfileStatus)
    assert isinstance(data["essential_function_count"], int)
    assert isinstance(data["total_essential_weight"], int)
    assert isinstance(data["committed_accommodation_cost_cents"], int)
    assert data["committed_accommodation_cost_cents"] >= 0


def assert_essential_function(data: dict):
    assert_common_fields(data, "EssentialFunction")
    assert is_valid_uuid(data["job_profile_id"])
    assert isinstance(data["function_code"], str) and data["function_code"]
    assert isinstance(data["description"], str)
    assert 1 <= data["criticality_weight"] <= 10
    assert 0 <= data["frequency_per_week"] <= 40
    assert isinstance(data["is_essential"], bool)
    assert isinstance(data["marginal_reassignable"], bool)
    assert data["status"] in _values(EssentialFunctionStatus)


def assert_accommodation_request(data: dict):
    assert_common_fields(data, "AccommodationRequest")
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["job_profile_id"])
    assert data["request_channel"] in [
        "WRITTEN",
        "VERBAL",
        "MANAGER_OBSERVED",
        "HR_INITIATED",
    ]
    assert isinstance(data["requested_accommodation_text"], str)
    assert isinstance(data["disability_obvious"], bool)
    assert data["stage"] in _values(RequestStage)
    assert data["confidentiality_posture"] in _values(ConfidentialityPosture)
    assert data["decision"] in _values(CaseDecision)
    for counter in (
        "interactive_round_count",
        "medical_doc_request_count",
        "medical_doc_request_limit",
        "documentation_budget_remaining",
        "cleared_option_count",
        "blocked_option_count",
        "review_cycle_index",
        "interactive_process_integrity_score",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must never go negative"
    assert 0 <= data["interactive_process_integrity_score"] <= 100


def assert_medical_doc_request(data: dict):
    assert_common_fields(data, "MedicalDocumentationRequest")
    assert is_valid_uuid(data["request_id"])
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert isinstance(data["scope_fields_requested"], list)
    assert len(data["scope_fields_requested"]) >= 1
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["due_date"], str)
    assert isinstance(data["is_second_opinion"], bool)
    assert data["status"] in _values(DocRequestStatus)


def assert_function_analysis(data: dict):
    assert_common_fields(data, "FunctionAnalysis")
    assert is_valid_uuid(data["request_id"])
    assert is_valid_uuid(data["essential_function_id"])
    assert is_valid_uuid(data["manager_id"])
    assert isinstance(data["can_perform_unaided"], bool)
    assert 0 <= data["limitation_severity"] <= 5
    assert data["proposed_treatment"] in [
        "NOT_LIMITED",
        "PERFORM_WITH_AID",
        "RESTRUCTURE",
        "REASSIGN_MARGINAL",
        "CANNOT_PERFORM",
    ]
    assert data["status"] in _values(FunctionAnalysisStatus)


def assert_accommodation_option(data: dict):
    assert_common_fields(data, "AccommodationOption")
    assert is_valid_uuid(data["request_id"])
    assert isinstance(data["option_code"], str) and data["option_code"]
    assert data["category"] in [
        "EQUIPMENT",
        "SCHEDULE_MODIFICATION",
        "TELEWORK",
        "JOB_RESTRUCTURING",
        "REASSIGNMENT",
        "LEAVE_AS_ACCOMMODATION",
        "POLICY_EXCEPTION",
    ]
    assert data["proposed_by_role"] in ["Employee", "AccommodationCoordinator"]
    assert isinstance(data["one_time_cost_cents"], int) and data["one_time_cost_cents"] >= 0
    assert isinstance(data["recurring_monthly_cost_cents"], int)
    assert data["recurring_monthly_cost_cents"] >= 0
    assert 0 <= data["implementation_days"] <= 365
    assert isinstance(data["coverage_function_ids"], list)
    assert isinstance(data["option_net_cost_cents"], int), (
        "option_net_cost_cents is a whole-cent integer"
    )
    assert isinstance(data["coverage_ratio"], (int, float))
    assert 0.0 <= float(data["coverage_ratio"]) <= 1.0
    assert isinstance(data["committed_cost_cents"], int)
    assert data["committed_cost_cents"] >= 0
    assert data["status"] in _values(OptionStatus)


def assert_hardship_assessment(data: dict):
    assert_common_fields(data, "UndueHardshipAssessment")
    assert is_valid_uuid(data["option_id"])
    assert data["assessment_basis"] in ["EMPLOYER_WIDE", "SITE_LOCAL"]
    assert isinstance(data["assessor_user_id"], str) and data["assessor_user_id"]
    assert isinstance(data["assessed_net_cost_cents"], int)
    assert isinstance(data["denominator_cents"], int) and data["denominator_cents"] > 0
    for numeric in (
        "budget_ratio",
        "budget_ratio_norm",
        "disruption_index",
        "lag_norm",
        "raw_hardship_score",
        "mitigation_credit_rate",
        "hardship_score",
    ):
        assert isinstance(data[numeric], (int, float)), f"{numeric} must be numeric"
    assert 0.0 <= float(data["budget_ratio_norm"]) <= 100.0
    assert 0.0 <= float(data["lag_norm"]) <= 100.0
    assert data["hardship_verdict"] in _values(HardshipVerdict)
    assert data["status"] in _values(AssessmentStatus)


def assert_trial_period(data: dict):
    assert_common_fields(data, "TrialPeriod")
    assert is_valid_uuid(data["request_id"])
    assert is_valid_uuid(data["option_id"])
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["end_date"] >= data["start_date"]
    assert 1 <= data["checkin_cadence_days"] <= 90
    assert data["scoring_mode"] in _values(ScoringMode)
    assert isinstance(data["review_count"], int) and data["review_count"] >= 0
    assert isinstance(data["extension_count"], int) and data["extension_count"] >= 0
    assert data["outcome"] in _values(TrialOutcome)
    assert data["status"] in _values(TrialStatus)
    if data["effectiveness_score"] is not None:
        assert isinstance(data["effectiveness_score"], (int, float))


def assert_effectiveness_review(data: dict):
    assert_journal_fields(data, "EffectivenessReview")
    assert is_valid_uuid(data["trial_period_id"])
    assert isinstance(data["review_index"], int) and data["review_index"] >= 1
    assert isinstance(data["review_date"], str)
    assert 0 <= data["employee_rating"] <= 10
    assert 0 <= data["manager_rating"] <= 10
    assert 0 <= data["objective_metric_pct"] <= 100
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]
    assert isinstance(data["review_composite"], (int, float))
    assert 0.0 <= float(data["review_composite"]) <= 10.0


def assert_denial_record(data: dict):
    assert_common_fields(data, "DenialRecord")
    assert is_valid_uuid(data["request_id"])
    assert data["denial_basis"] in [
        "UNDUE_HARDSHIP",
        "DIRECT_THREAT",
        "NOT_QUALIFIED",
        "NO_DISABILITY_NEXUS",
        "INSUFFICIENT_DOCUMENTATION",
        "FAILURE_TO_COOPERATE",
    ]
    assert isinstance(data["rationale_text"], str) and data["rationale_text"].strip()
    assert isinstance(data["rejected_option_ids"], list)
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["appeal_deadline_date"], str)
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0
    assert data["status"] in _values(DenialStatus)


def assert_appeal(data: dict):
    assert_common_fields(data, "Appeal")
    assert is_valid_uuid(data["denial_record_id"])
    assert isinstance(data["grounds_text"], str)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["supplement_count"], int) and data["supplement_count"] >= 0
    assert isinstance(data["stay_count"], int) and data["stay_count"] >= 0
    assert data["outcome"] in _values(AppealOutcome)
    assert data["status"] in _values(AppealStatus)


def assert_absence_record(data: dict):
    assert_common_fields(data, "AbsenceRecord")
    assert is_valid_uuid(data["employee_id"])
    assert data["record_type"] in [
        "FMLA_CONTINUOUS",
        "FMLA_INTERMITTENT",
        "STATE_LEAVE",
        "WC_RESTRICTION",
    ]
    assert data["end_date"] > data["start_date"], "end_date is exclusive and must be later"
    assert 0 <= data["weekly_intermittent_days"] <= 7
    assert 0 <= data["restriction_severity"] <= 5
    assert isinstance(data["modified_duty_available"], bool)
    assert data["status"] in _values(AbsenceStatus)


def assert_medical_disclosure(data: dict):
    assert_journal_fields(data, "MedicalDisclosure")
    assert is_valid_uuid(data["request_id"])
    assert isinstance(data["disclosed_to_role"], str)
    assert isinstance(data["disclosed_to_user_id"], str)
    assert isinstance(data["disclosure_purpose"], str)
    assert isinstance(data["fields_disclosed"], list) and data["fields_disclosed"]
    assert isinstance(data["authorized"], bool)
    assert isinstance(data["logged_by_user_id"], str) and data["logged_by_user_id"]


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_documentation_budget_invariant(case: dict):
    """count + remaining == limit, and remaining is floored at zero."""
    assert case["documentation_budget_remaining"] >= 0
    assert (
        case["medical_doc_request_count"] + case["documentation_budget_remaining"]
        == case["medical_doc_request_limit"]
    ), (
        "medical_doc_request_count + documentation_budget_remaining must equal "
        f"medical_doc_request_limit, got {case['medical_doc_request_count']} + "
        f"{case['documentation_budget_remaining']} vs {case['medical_doc_request_limit']}"
    )


def assert_ledger_matches_options(profile: dict, options: list):
    """The profile ledger equals the sum of committed_cost_cents over the
    options in SELECTED or IMPLEMENTED, and everything else contributes zero."""
    expected = 0
    for option in options:
        if option["status"] in ("SELECTED", "IMPLEMENTED"):
            expected += option["committed_cost_cents"]
        else:
            assert option["committed_cost_cents"] == 0, (
                f"option {option['option_code']} in {option['status']} must hold "
                "committed_cost_cents 0"
            )
    assert profile["committed_accommodation_cost_cents"] == expected, (
        "committed_accommodation_cost_cents must equal the sum over SELECTED and "
        f"IMPLEMENTED options: expected {expected}, got "
        f"{profile['committed_accommodation_cost_cents']}"
    )


def assert_calendar_date(value, expected: str, label: str = "date"):
    """A `_date` field must fall on the expected calendar day.

    The PRD renders calendar dates in YYYY-MM-DD form, so the day itself is the
    contract; this tolerates a fuller instant serialisation of the same day.
    """
    assert value is not None, f"{label} must be set"
    assert str(value).startswith(expected), (
        f"{label} must fall on {expected}, got {value!r}"
    )
