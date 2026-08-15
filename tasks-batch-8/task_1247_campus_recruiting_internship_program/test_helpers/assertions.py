"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def assert_recruiting_season(data: dict):
    _assert_common_fields(data, "RecruitingSeason")
    assert data["status"] in [
        "DRAFT", "OPEN", "SELECTION", "OFFER_PERIOD", "INTERN_ACTIVE", "CLOSED",
    ]
    assert isinstance(data["shortlist_score_threshold"], int)
    assert isinstance(data["stipend_budget_cents"], int)
    assert isinstance(data["stipend_reserved_cents"], int)
    assert isinstance(data["stipend_disbursed_cents"], int)
    assert isinstance(data["applications_total_count"], int)
    assert isinstance(data["offers_extended_count"], int)
    assert isinstance(data["offers_accepted_count"], int)
    assert isinstance(data["completed_assignments_count"], int)
    assert isinstance(data["return_offers_extended_count"], int)
    assert isinstance(data["return_offers_accepted_count"], int)


def assert_school_target(data: dict):
    _assert_common_fields(data, "SchoolTarget")
    assert data["status"] in ["ACTIVE", "DROPPED"]
    assert data["tier"] in ["CORE", "TARGET", "EXPLORATORY"]
    assert data["stipend_region"] in ["METRO", "REGIONAL", "REMOTE"]
    assert isinstance(data["application_cap"], int) and data["application_cap"] >= 1


def assert_campus_event(data: dict):
    _assert_common_fields(data, "CampusEvent")
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert data["event_type"] in ["CAREER_FAIR", "INFO_SESSION", "RESUME_DROP"]


def assert_candidate(data: dict):
    _assert_common_fields(data, "Candidate")
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["is_alumnus"], bool)


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert data["status"] in [
        "SUBMITTED", "SHORTLISTED", "INTERVIEW_SCHEDULED", "DECISION_PENDING",
        "OFFER_PENDING", "ACCEPTED", "SCREENED_OUT", "REJECTED", "WITHDRAWN",
        "EXPIRED",
    ]


def assert_employee(data: dict):
    _assert_common_fields(data, "Employee")
    assert isinstance(data["assigned_intern_count"], int)
    assert isinstance(data["can_evaluate"], bool)
    assert isinstance(data["can_mentor"], bool)
    assert isinstance(data["calibrated"], bool)


def assert_interview_day(data: dict):
    _assert_common_fields(data, "InterviewDay")
    assert data["status"] in ["OPEN", "LOCKED", "COMPLETED"]
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_interview_slot(data: dict):
    _assert_common_fields(data, "InterviewSlot")
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED", "NO_SHOW"]


def assert_evaluation(data: dict):
    _assert_common_fields(data, "Evaluation")
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5
    assert data["recommendation"] in [
        "STRONG_HIRE", "HIRE", "LEAN_NO", "NO_HIRE",
    ]


def assert_offer(data: dict):
    _assert_common_fields(data, "Offer")
    assert data["status"] in [
        "DRAFT", "EXTENDED", "ACCEPTED", "DECLINED", "EXPIRED", "RESCINDED",
    ]
    assert isinstance(data["weekly_rate_cents"], int) and data["weekly_rate_cents"] > 0
    assert isinstance(data["duration_weeks"], int) and data["duration_weeks"] >= 1
    assert isinstance(data["extension_hours_granted"], int)


def assert_stipend_disbursement(data: dict):
    _assert_common_fields(data, "StipendDisbursement")
    assert data["status"] in ["RESERVED", "DISBURSED", "RELEASED"]
    assert isinstance(data["amount_cents"], int)


def assert_intern_project(data: dict):
    _assert_common_fields(data, "InternProject")
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_project_assignment(data: dict):
    _assert_common_fields(data, "ProjectAssignment")
    assert data["status"] in ["ACTIVE", "COMPLETED", "UNASSIGNED"]
    assert data["return_offer_decision"] in ["NONE", "EXTENDED", "NO_OFFER"]
    assert data["return_offer_outcome"] in ["NONE", "ACCEPTED", "DECLINED"]


def assert_intern_evaluation(data: dict):
    """Append-only record: id + created_at present; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "InternEvaluation.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "InternEvaluation.created_at must be ISO 8601"
    )
    assert "version" not in data, "InternEvaluation must not carry version"
    assert "updated_at" not in data, "InternEvaluation must not carry updated_at"
    assert data["eval_type"] in ["MID", "FINAL"]
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert isinstance(data["would_rehire"], bool)


def assert_stipend_ledger_invariants(season: dict):
    """Season stipend ledger must be non-negative and bounded by the pool."""
    assert season["stipend_reserved_cents"] >= 0
    assert season["stipend_disbursed_cents"] >= 0
    assert (
        season["stipend_reserved_cents"] + season["stipend_disbursed_cents"]
        <= season["stipend_budget_cents"]
    )
