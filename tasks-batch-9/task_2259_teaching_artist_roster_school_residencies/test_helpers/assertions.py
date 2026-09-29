"""Entity assertions and domain invariant checkers.

Primary resources carry id/created_at/updated_at/version. The four
append-only observation types carry only id and created_at, so their
assertions never demand updated_at or version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BLACKOUT_TYPES,
    CANCEL_REASONS,
    COLLABORATION_EXPECTATIONS,
    DISCIPLINES,
    EVALUATION_TYPES,
    GRADE_BANDS,
    HEADCOUNT_BASES,
    SCREENING_TYPES,
    STRANDS,
)


# --------------------------------------------------------------------------
# Shared shape helpers
# --------------------------------------------------------------------------
def assert_common_primary_fields(data: dict) -> None:
    """id + created_at + updated_at + version for a primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1 or more, got {data['version']}"


def assert_append_only_fields(data: dict) -> None:
    """id + created_at only — updated_at and version must be absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert "updated_at" not in data, "append-only records must not carry updated_at"
    assert "version" not in data, "append-only records must not carry version"


def assert_envelope_meta(body: dict) -> None:
    meta = body.get("meta", {})
    assert str(meta.get("api_request_id", "")).startswith(
        "req_"
    ), f"api_request_id must start with req_, got {meta.get('api_request_id')}"
    assert is_iso8601_timestamp(
        meta.get("api_request_timestamp", "")
    ), "api_request_timestamp must be an ISO 8601 UTC timestamp"


def assert_two_decimals(value, label: str = "value") -> None:
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == float(value), f"{label} must carry 2 decimals"


def assert_one_decimal(value, label: str = "value") -> None:
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 1) == float(value), f"{label} must carry 1 decimal"


def assert_whole_cents(value, label: str = "cents") -> None:
    assert isinstance(value, int), f"{label} must be an integer number of cents"


# --------------------------------------------------------------------------
# Primary resources
# --------------------------------------------------------------------------
def assert_school_partner(data: dict) -> None:
    assert_common_primary_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["district_name"], str)
    assert isinstance(data["grade_span"], str)
    assert data["concurrent_session_capacity"] >= 1
    assert data["total_enrollment"] >= 1
    for share in ("frl_pct", "ell_pct", "iep_pct"):
        assert 0.0 <= float(data[share]) <= 1.0, f"{share} must be within 0.00–1.00"
    assert data["partnership_health"] in ("HEALTHY", "WATCH", "INTAKE_SUSPENDED")
    assert isinstance(data["open_residency_count"], int)


def assert_teaching_artist(data: dict) -> None:
    assert_common_primary_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["primary_discipline"] in DISCIPLINES
    assert isinstance(data["secondary_disciplines"], list)
    assert isinstance(data["grade_bands"], list) and len(data["grade_bands"]) >= 1
    for band in data["grade_bands"]:
        assert band in GRADE_BANDS
    assert isinstance(data["languages"], list) and len(data["languages"]) >= 1
    assert data["vetting_status"] in (
        "APPLIED", "PORTFOLIO_REVIEW", "DEMO_SCHEDULED", "DEMO_FAILED",
        "DEMO_PASSED", "SCREENING_PENDING", "CLEARED", "DECLINED", "SCREEN_FAILED",
    )
    assert data["roster_status"] in (
        "NOT_LISTED", "ACTIVE", "PROBATION", "SUSPENDED", "RETIRED",
    )
    assert data["roster_tier_assigned"] in ("APPRENTICE", "TEACHING_ARTIST", "MASTER")
    assert data["roster_tier_effective"] in ("APPRENTICE", "TEACHING_ARTIST", "MASTER")
    assert data["clearance_status"] in ("NONE", "CLEARED", "EXPIRED")
    assert isinstance(data["portfolio_review_count"], int)
    assert isinstance(data["demo_attempt_count"], int)
    assert isinstance(data["lifetime_delivered_count"], int)
    assert isinstance(data["no_show_count"], int)
    assert 0 <= data["reliability_bps_rolling"] <= 10000
    assert 0 <= data["reliability_bps_program_year"] <= 10000


def assert_arts_standard(data: dict) -> None:
    assert_common_primary_fields(data)
    assert 3 <= len(data["code"]) <= 24, "code must be 3 to 24 characters"
    assert data["discipline"] in DISCIPLINES
    assert data["grade_band"] in GRADE_BANDS
    assert data["strand"] in STRANDS
    assert isinstance(data["description"], str)


def assert_residency(data: dict) -> None:
    assert_common_primary_fields(data)
    assert is_valid_uuid(data["school_partner_id"])
    assert isinstance(data["title"], str)
    assert data["discipline"] in DISCIPLINES
    assert data["grade_band"] in GRADE_BANDS
    assert isinstance(data["instruction_language"], str)
    assert 1 <= data["contracted_session_count"] <= 60
    assert 30 <= data["session_length_minutes"] <= 120
    assert data["session_length_minutes"] % 5 == 0
    assert data["budget_cents"] >= 1
    assert data["collaboration_expectation"] in COLLABORATION_EXPECTATIONS
    assert 0 <= data["co_planning_hours_required"] <= 20
    assert isinstance(data["required_strands"], list) and data["required_strands"]
    for strand in data["required_strands"]:
        assert strand in STRANDS
    assert data["enrolled_student_count"] >= 1
    assert data["status"] in (
        "DRAFT", "APPROVED", "ACTIVE", "SUSPENDED", "COMPLETED", "CLOSED", "CANCELLED",
    )
    assert data["staffing_status"] in ("LEAD_VACANT", "AT_RISK", "STAFFED")
    assert_residency_ledgers(data)


def assert_residency_ledgers(data: dict) -> None:
    """The two conserved quantities of a residency (PRD §2.12)."""
    buckets = (
        data["sessions_unscheduled_count"]
        + data["sessions_open_count"]
        + data["sessions_delivered_count"]
        + data["sessions_forfeited_count"]
        + data["makeup_credits_outstanding"]
    )
    if data["status"] == "DRAFT":
        # Before approval the allotment is not yet initialized.
        assert buckets <= data["contracted_session_count"]
    else:
        assert buckets == data["contracted_session_count"], (
            "the five session buckets must sum to contracted_session_count, "
            f"got {buckets} vs {data['contracted_session_count']}"
        )
    assert data["vacated_session_count"] <= data["sessions_open_count"]
    for field in ("encumbered_cents", "disbursed_cents", "available_cents",
                  "budget_cents", "earned_to_date_cents", "projected_cost_cents"):
        assert_whole_cents(data[field], field)
    if data["status"] != "DRAFT":
        money = (
            data["available_cents"] + data["encumbered_cents"] + data["disbursed_cents"]
        )
        assert money == data["budget_cents"], (
            "available plus encumbered plus disbursed must equal budget_cents, "
            f"got {money} vs {data['budget_cents']}"
        )
    assert data["available_cents"] >= 0, "available_cents must never go negative"
    if data.get("evaluation_index") is not None:
        assert 0.0 <= float(data["evaluation_index"]) <= 100.0
        assert_one_decimal(data["evaluation_index"], "evaluation_index")


def assert_lesson_plan(data: dict) -> None:
    assert_common_primary_fields(data)
    assert is_valid_uuid(data["residency_id"])
    assert isinstance(data["title"], str)
    assert 1 <= data["session_sequence_no"] <= 60
    assert isinstance(data["standard_codes"], list) and data["standard_codes"]
    assert isinstance(data["covered_strands"], list)
    for strand in data["covered_strands"]:
        assert strand in STRANDS
    assert data["status"] in ("SUBMITTED", "CHANGES_REQUESTED", "ALIGNED", "ARCHIVED")
    assert 0 <= data["revision_round"] <= 3


def assert_session(data: dict) -> None:
    assert_common_primary_fields(data)
    assert is_valid_uuid(data["residency_id"])
    assert isinstance(data["session_date"], str) and len(data["session_date"]) == 10
    assert isinstance(data["start_time"], str) and len(data["start_time"]) == 5
    assert isinstance(data["end_time"], str) and len(data["end_time"]) == 5
    assert data["end_time"] > data["start_time"], "end_time must be after start_time"
    assert data["session_type"] in ("REGULAR", "MAKEUP")
    assert data["status"] in (
        "PLANNED", "CONFIRMED", "VACATED",
        "DELIVERED", "CANCELLED_SCHOOL", "CANCELLED_ARTIST",
    )
    assert isinstance(data["is_substitute"], bool)
    assert isinstance(data["co_planning_completed"], bool)
    assert isinstance(data["makeup_eligible"], bool)
    assert isinstance(data["makeup_consumed"], bool)
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in CANCEL_REASONS
    for field in ("fee_cents", "travel_reimbursement_cents",
                  "materials_reimbursement_cents", "payable_cents",
                  "encumbered_cents"):
        assert_whole_cents(data[field], field)


def assert_payment_voucher(data: dict) -> None:
    assert_common_primary_fields(data)
    assert is_valid_uuid(data["teaching_artist_id"])
    assert is_valid_uuid(data["residency_id"])
    assert isinstance(data["session_ids"], list) and data["session_ids"]
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "VOIDED")
    assert data["fiscal_review_status"] in ("PENDING", "PASSED", "FAILED")
    assert data["program_review_status"] in ("PENDING", "PASSED", "FAILED")
    for field in ("session_fee_subtotal_cents", "travel_reimbursement_cents",
                  "materials_reimbursement_cents", "total_cents"):
        assert_whole_cents(data[field], field)
    expected_total = (
        data["session_fee_subtotal_cents"]
        + data["travel_reimbursement_cents"]
        + data["materials_reimbursement_cents"]
    )
    assert data["total_cents"] == expected_total, (
        "total_cents must be the three subtotals added together, "
        f"got {data['total_cents']} vs {expected_total}"
    )


def assert_funder_report(data: dict) -> None:
    assert_common_primary_fields(data)
    assert isinstance(data["funder_name"], str)
    assert isinstance(data["grant_code"], str)
    assert isinstance(data["scope_residency_ids"], list)
    assert data["scope_residency_ids"], "scope_residency_ids must be non-empty"
    assert data["headcount_basis"] in HEADCOUNT_BASES
    assert data["status"] in ("DRAFT", "COMPILED", "CERTIFIED")
    for field in ("sessions_delivered_total", "students_served",
                  "frl_students_reached", "ell_students_reached",
                  "iep_students_reached"):
        assert isinstance(data[field], int) and data[field] >= 0
    for field in ("direct_cost_cents", "indirect_cost_cents",
                  "total_spend_cents", "cost_per_student_cents"):
        assert_whole_cents(data[field], field)
    assert data["total_spend_cents"] == (
        data["direct_cost_cents"] + data["indirect_cost_cents"]
    ), "total_spend_cents must be direct cost plus indirect cost"


# --------------------------------------------------------------------------
# Append-only observations
# --------------------------------------------------------------------------
def assert_calendar_blackout(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["school_partner_id"])
    assert data["blackout_type"] in BLACKOUT_TYPES
    assert data["end_date"] >= data["start_date"], "end_date must not precede start_date"


def assert_portfolio_review(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["teaching_artist_id"])
    assert isinstance(data["reviewer_user_id"], str)
    for field in ("artistic_quality_score", "pedagogical_clarity_score",
                  "cultural_responsiveness_score"):
        assert 1.0 <= float(data[field]) <= 5.0, f"{field} must be 1.0 to 5.0"
    assert_two_decimals(data["composite_score"], "composite_score")
    assert data["recommendation"] in ("ADVANCE", "DECLINE")


def assert_background_screening(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["teaching_artist_id"])
    assert data["screening_type"] in SCREENING_TYPES
    assert data["outcome"] in ("CLEARED", "FAILED")
    assert isinstance(data["effective_on"], str)
    if data["outcome"] == "CLEARED":
        assert data["expires_on"] is not None
        assert data["expires_on"] > data["effective_on"]
    else:
        assert data["expires_on"] is None
    assert isinstance(data["superseded"], bool)


def assert_evaluation_record(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert data["evaluation_type"] in EVALUATION_TYPES
    assert isinstance(data["evaluator_user_id"], str)
    if data["evaluation_type"] == "OBSERVATION_RUBRIC":
        for field in ("rubric_engagement_score", "rubric_craft_score",
                      "rubric_standards_evidence_score"):
            assert 1 <= data[field] <= 4, f"{field} must be a whole number 1 to 4"
        assert data["teacher_survey_score"] is None
        assert data["student_work_artifact_count"] is None
        assert_two_decimals(data["rubric_composite"], "rubric_composite")
    elif data["evaluation_type"] == "TEACHER_SURVEY":
        assert 1 <= data["teacher_survey_score"] <= 5
        assert data["rubric_engagement_score"] is None
        assert data["rubric_craft_score"] is None
        assert data["rubric_standards_evidence_score"] is None
        assert data["student_work_artifact_count"] is None
        assert data["rubric_composite"] is None
    else:
        assert data["student_work_artifact_count"] >= 0
        assert data["rubric_engagement_score"] is None
        assert data["rubric_craft_score"] is None
        assert data["rubric_standards_evidence_score"] is None
        assert data["teacher_survey_score"] is None
        assert data["rubric_composite"] is None
