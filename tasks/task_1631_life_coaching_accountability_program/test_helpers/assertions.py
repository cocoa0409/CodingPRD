"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_full_resource_common(data: dict, entity_name: str):
    """Fields every primary resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_name}.version must be a positive integer"


def _assert_append_only_common(data: dict, entity_name: str):
    """Append-style records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


def assert_coach(data: dict):
    _assert_full_resource_common(data, "Coach")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["credential_level"] in ("ACC", "PCC", "MCC")
    assert data["credential_status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "EXPIRED", "REVOKED")
    assert data["ethics_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["max_concurrent_clients"], int) \
        and data["max_concurrent_clients"] >= 1


def assert_client(data: dict):
    _assert_full_resource_common(data, "Client")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["client_status"] == "ACTIVE"
    score = data["engagement_score"]
    assert isinstance(score, int) and 0 <= score <= 100, \
        f"engagement_score must be an integer in 0..100, got {score!r}"


def assert_program_tier(data: dict):
    _assert_full_resource_common(data, "ProgramTier")
    assert isinstance(data["tier_code"], str) and data["tier_code"]
    assert data["tier_type"] in ("SINGLE", "PACKAGE", "MEMBERSHIP")
    assert isinstance(data["session_count"], int) and data["session_count"] >= 1
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["duration_days"], int) and data["duration_days"] >= 1
    assert isinstance(data["installment_count_allowed"], int) \
        and data["installment_count_allowed"] >= 1
    assert isinstance(data["reschedule_cap"], int) and data["reschedule_cap"] >= 0
    assert data["tier_status"] in ("ACTIVE", "RETIRED")


def assert_discovery_call(data: dict):
    _assert_full_resource_common(data, "DiscoveryCall")
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("coach_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert isinstance(data["duration_minutes"], int) \
        and data["duration_minutes"] >= 15
    assert data["call_status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_fit_assessment(data: dict):
    _assert_append_only_common(data, "FitAssessment")
    assert is_valid_uuid(data.get("discovery_call_id", ""))
    assert data["scope_fit"] in ("WITHIN_SCOPE", "OUTSIDE_SCOPE")
    assert isinstance(data["commitment_score"], int) \
        and 0 <= data["commitment_score"] <= 100
    assert data["outcome"] in ("PROCEED", "REFER_OUT")
    assert is_valid_uuid(data.get("assessor_coach_id", ""))


def assert_enrollment(data: dict):
    _assert_full_resource_common(data, "Enrollment")
    for key in ("client_id", "coach_id", "program_tier_id", "discovery_call_id"):
        assert is_valid_uuid(data.get(key, "")), f"Enrollment.{key} must be a UUID"
    assert data["lifecycle_status"] in (
        "PENDING_PAYMENT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED", "REFUNDED")
    assert data["payment_status"] in ("CURRENT", "DELINQUENT", "DEFAULTED")
    assert isinstance(data["sessions_total"], int) and data["sessions_total"] >= 1
    assert isinstance(data["sessions_total_price_basis"], int)
    assert isinstance(data["sessions_consumed"], int) \
        and data["sessions_consumed"] >= 0
    assert isinstance(data["sessions_remaining"], int) \
        and data["sessions_remaining"] >= 0
    assert isinstance(data["late_reschedules_used"], int) \
        and data["late_reschedules_used"] >= 0
    assert isinstance(data["pauses_used"], int) and data["pauses_used"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0


def assert_installment(data: dict):
    _assert_append_only_common(data, "Installment")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["installment_status"] in ("PENDING", "PAID", "LATE")


def assert_session(data: dict):
    _assert_full_resource_common(data, "Session")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("coach_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert isinstance(data["duration_minutes"], int) \
        and 30 <= data["duration_minutes"] <= 120
    assert data["session_status"] in (
        "SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED", "FORFEITED")
    assert data.get("successor_session_id") is None \
        or is_valid_uuid(data["successor_session_id"])
    assert isinstance(data["is_late_reschedule"], bool)


def assert_goal(data: dict):
    _assert_full_resource_common(data, "Goal")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["target_count"], int) and data["target_count"] >= 1
    assert data["goal_status"] in ("OPEN", "ACHIEVED", "ABANDONED")
    assert isinstance(data["achieved_count"], int) and data["achieved_count"] >= 0


def assert_habit_check_in(data: dict):
    _assert_append_only_common(data, "HabitCheckIn")
    assert is_valid_uuid(data.get("goal_id", ""))
    assert isinstance(data["check_in_date"], str) and data["check_in_date"]
    assert isinstance(data["completed"], bool)


def assert_cohort(data: dict):
    _assert_full_resource_common(data, "Cohort")
    assert is_valid_uuid(data.get("coach_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 2
    assert isinstance(data["window_start"], str) and data["window_start"]
    assert isinstance(data["window_end"], str) and data["window_end"]
    assert data["cohort_status"] in (
        "DRAFT", "OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_cohort_membership(data: dict):
    _assert_append_only_common(data, "CohortMembership")
    assert is_valid_uuid(data.get("cohort_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["member_status"] in ("ACTIVE", "WAITLISTED", "REMOVED")
    assert is_iso8601_timestamp(data.get("joined_at", ""))


def assert_testimonial(data: dict):
    _assert_full_resource_common(data, "Testimonial")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["outcome_rating"], int) \
        and 1 <= data["outcome_rating"] <= 5
    assert isinstance(data["body_text"], str)
    assert data["consent_status"] in ("PENDING", "CONSENTED", "DECLINED", "REVOKED")
    assert data["publish_status"] in ("HIDDEN", "PUBLISHED")


def assert_refund_request(data: dict):
    _assert_full_resource_common(data, "RefundRequest")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["basis"] in ("COOLING_OFF", "PRO_RATA")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["refund_status"] in ("PENDING", "APPROVED", "DENIED")


def assert_session_credit_invariant(enrollment: dict, scheduled_count: int,
                                    forfeited_count: int):
    """PRD §3.4 credit accounting: sessions_total == sessions_consumed +
    sessions_remaining + count(SCHEDULED) + count(FORFEITED)."""
    total = enrollment["sessions_total"]
    consumed = enrollment["sessions_consumed"]
    remaining = enrollment["sessions_remaining"]
    assert consumed + remaining + scheduled_count + forfeited_count == total, (
        f"session credit invariant violated: consumed={consumed} "
        f"remaining={remaining} scheduled={scheduled_count} "
        f"forfeited={forfeited_count} total={total}"
    )
