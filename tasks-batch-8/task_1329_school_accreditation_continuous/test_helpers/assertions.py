"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Shared field-group helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight_fields(data: dict):
    """Standard, SurveyResponse, Payment, FeeSchedule carry id and created_at
    only; updated_at and version are absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "updated_at must be absent on lightweight records"
    assert "version" not in data, "version must be absent on lightweight records"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_institution_system(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["system_type"] in ("DISTRICT", "NETWORK", "SINGLE_SCHOOL")
    assert data["accreditation_status"] in (
        "CANDIDATE", "ACCREDITED", "ON_PROBATION", "ACCREDITATION_WITHDRAWN")
    assert isinstance(data["fee_credit_cents"], int)
    assert "current_term_id" in data


def assert_campus(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("system_id", "")), "system_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["enrollment"], int) and data["enrollment"] >= 1
    assert data["campus_status"] in ("IN_SCOPE", "OUT_OF_SCOPE", "WITHDRAWN")
    assert "composite_index_pct" in data


def assert_standard(data: dict):
    _assert_lightweight_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["domain"] in ("LEADERSHIP", "LEARNING", "RESOURCES")
    assert isinstance(data["weight_pct"], int) and 1 <= data["weight_pct"] <= 100
    assert isinstance(data["evidence_min_items"], int) and data["evidence_min_items"] >= 0


def assert_term(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("system_id", "")), "system_id must be a UUID"
    assert isinstance(data["term_length_years"], int) and data["term_length_years"] in (5, 6)
    assert data["status"] in (
        "PREPARATION", "SELF_STUDY", "REVIEW", "DECISION", "TERM_ACTIVE",
        "INTERIM_MONITORING", "RENEWAL", "CLOSED")
    assert data["decision_outcome"] in (
        "NONE", "ACCREDITED", "ACCREDITED_WITH_STIPULATIONS", "DENIED")


def assert_rating(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("term_id", "")), "term_id must be a UUID"
    assert is_valid_uuid(data.get("campus_id", "")), "campus_id must be a UUID"
    assert is_valid_uuid(data.get("standard_id", "")), "standard_id must be a UUID"
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 4
    assert data["status"] in ("DRAFT", "SUBMITTED", "FINALIZED", "REOPENED")
    assert "finalized_at" in data


def assert_evidence_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("rating_id", "")), "rating_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["artifact_uri"], str) and data["artifact_uri"]
    assert isinstance(data["submitted_by_user_id"], str)
    assert data["review_status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_survey_instrument(data: dict):
    _assert_common_fields(data)
    assert data["stakeholder_group"] in ("STUDENTS", "PARENTS", "STAFF", "BOARD")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["min_participation_pct"], int) \
        and 1 <= data["min_participation_pct"] <= 100


def assert_survey_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("term_id", "")), "term_id must be a UUID"
    assert is_valid_uuid(data.get("campus_id", "")), "campus_id must be a UUID"
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    assert isinstance(data["eligible_count"], int) and data["eligible_count"] >= 1
    assert isinstance(data["response_count"], int) and data["response_count"] >= 0
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "INVALIDATED")


def assert_survey_response(data: dict):
    _assert_lightweight_fields(data)
    assert is_valid_uuid(data.get("window_id", "")), "window_id must be a UUID"
    assert isinstance(data["respondent_token"], str) and data["respondent_token"]


def assert_improvement_goal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("term_id", "")), "term_id must be a UUID"
    assert is_valid_uuid(data.get("standard_id", "")), "standard_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert data["direction"] in ("INCREASE", "DECREASE")
    assert isinstance(data["baseline_value"], (int, float))
    assert isinstance(data["target_value"], (int, float))
    assert isinstance(data["current_value"], (int, float))
    assert isinstance(data["attainment_pct"], (int, float))
    assert data["status"] in ("PROPOSED", "ADOPTED", "MONITORING", "ACHIEVED", "ABANDONED")


def assert_progress_indicator(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("goal_id", "")), "goal_id must be a UUID"
    assert isinstance(data["value"], (int, float))


def assert_visit_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("term_id", "")), "term_id must be a UUID"
    assert is_valid_uuid(data.get("lead_reviewer_id", "")), "lead_reviewer_id must be a UUID"
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "IN_FIELD", "REPORT_DRAFT", "REPORT_ISSUED", "CANCELLED")


def assert_reviewer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["reviewer_status"] in ("AVAILABLE", "ON_ASSIGNMENT", "INACTIVE")
    assert isinstance(data["conflict_system_ids"], list)


def assert_visit_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("visit_id", "")), "visit_id must be a UUID"
    assert is_valid_uuid(data.get("reviewer_id", "")), "reviewer_id must be a UUID"
    assert data["role_on_team"] in ("CHAIR", "MEMBER", "OBSERVER")


def assert_visit_finding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("visit_id", "")), "visit_id must be a UUID"
    assert is_valid_uuid(data.get("standard_id", "")), "standard_id must be a UUID"
    assert data["severity"] in ("COMMENDATION", "RECOMMENDATION", "REQUIRED_ACTION")
    assert isinstance(data["narrative"], str)
    assert data["status"] in ("DRAFT", "ISSUED", "SUPERSEDED")


def assert_action_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("finding_id", "")), "finding_id must be a UUID"
    assert data["status"] in ("OPEN", "SUBMITTED", "VERIFIED", "OVERDUE", "WAIVED")
    assert data.get("follow_up_months") in (6, 12, 18)
    assert "due_date" in data
    assert "verified_by_user_id" in data


def assert_interim_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("term_id", "")), "term_id must be a UUID"
    assert isinstance(data["report_year"], int) and data["report_year"] >= 1
    assert "due_date" in data
    assert "submitted_at" in data
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED", "LATE")


def assert_fee_schedule(data: dict):
    _assert_lightweight_fields(data)
    for field in ("base_system_fee_cents", "per_campus_fee_cents",
                  "large_campus_fee_cents", "visit_day_rate_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["large_campus_threshold"], int)


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("system_id", "")), "system_id must be a UUID"
    assert isinstance(data["billing_year"], int)
    assert data["invoice_type"] in ("ANNUAL_FEE", "VISIT_FEE", "RENEWAL_FEE")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "VOID")
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"


def assert_payment(data: dict):
    _assert_lightweight_fields(data)
    assert is_valid_uuid(data.get("invoice_id", "")), "invoice_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
