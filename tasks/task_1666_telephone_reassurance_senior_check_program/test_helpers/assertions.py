"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Every resource carries id (UUID, no prefix), created_at/updated_at
    (ISO 8601 UTC, three fractional digits) and an integer version starting
    at 1 (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["total_capacity"], int) and 1 <= data["total_capacity"] <= 10000
    assert isinstance(data["max_reserve_slots"], int)
    assert isinstance(data["no_answer_threshold"], int)
    assert isinstance(data["escalation_retry_hours"], int)
    assert isinstance(data["contact_phase_hours"], int)
    assert isinstance(data["offer_ttl_hours"], int)
    assert isinstance(data["reapply_cooling_days"], int)
    assert isinstance(data["survey_valid_days"], int)
    assert isinstance(data["doc_buffer_minutes"], int)
    assert isinstance(data["current_policy_version"], str)
    assert data["intake_posture"] in ("OPEN", "PAUSED")
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert isinstance(data["waiting_count"], int) and data["waiting_count"] >= 0
    assert isinstance(data["promotion_epoch"], int) and data["promotion_epoch"] >= 0


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["address"], str)
    assert isinstance(data["primary_language"], str)
    assert data["referral_source"] in ("SELF", "FAMILY", "APS_REFERRAL", "HOSPITAL_DISCHARGE", "OTHER_PROVIDER")
    assert data["age_band"] in ("AGE_65_74", "AGE_75_84", "AGE_85_PLUS")
    assert isinstance(data["lives_alone"], bool)
    assert data["mobility"] in ("NONE", "LIMITED", "SEVERE")
    assert isinstance(data["cognitive_concern"], bool)
    assert isinstance(data["chronic_conditions_count"], int)
    assert isinstance(data["recent_hospitalization"], bool)
    assert isinstance(data["recent_bereavement"], bool)
    assert "acuity_score" in data
    assert "acuity_tier" in data
    assert "rolling_acuity_score" in data
    assert "rolling_acuity_tier" in data
    assert "effective_acuity_tier" in data
    assert data["status"] in (
        "APPLICANT", "UNDER_REVIEW", "WAITLISTED", "ENROLLED", "SUSPENDED",
        "WELFARE_HOLD", "DENIED", "DISENROLLED", "EXITED",
    )
    assert isinstance(data["consecutive_no_answer_count"], int) and data["consecutive_no_answer_count"] >= 0
    assert "open_escalation_id" in data
    assert isinstance(data["coverage_deficient"], bool)
    assert "enrolled_at" in data
    assert "last_status_change_at" in data


def assert_emergency_contact(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["relationship"], str)
    assert data["contact_rank"] in ("PRIMARY", "SECONDARY")
    assert isinstance(data["accepts_24h"], bool)
    assert data["status"] in ("ACTIVE", "UNREACHABLE", "REMOVED")


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert data["status"] in ("WAITING", "OFFERED", "ACCEPTED", "REMOVED")
    assert "waitlist_entered_at" in data
    assert "offered_at" in data
    assert "offer_expires_at" in data
    assert isinstance(data["declines_count"], int) and data["declines_count"] >= 0
    assert isinstance(data["expires_count"], int) and data["expires_count"] >= 0
    assert "priority_score_at_offer" in data
    assert "removal_reason" in data


def assert_volunteer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["languages"], list)
    assert isinstance(data["max_weekly_minutes"], int) and 60 <= data["max_weekly_minutes"] <= 600
    assert data["status"] in ("APPLICANT", "IN_TRAINING", "ACTIVE", "INACTIVE", "LAPSED", "SEPARATED")
    assert "reliability_windowed" in data
    assert "reliability_streak_adj" in data
    assert data["reliability_tier"] in ("GOLD", "SILVER", "BRONZE", "PROBATION")
    assert data["max_concurrent_assignments"] in (12, 10, 8, 4)
    assert isinstance(data["current_week_minutes"], int) and data["current_week_minutes"] >= 0


def assert_availability_window(data: dict):
    _assert_common(data)
    assert isinstance(data["volunteer_id"], str)
    assert data["weekday"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["effective_from"], str)
    assert "effective_to" in data


def assert_training_record(data: dict):
    _assert_common(data)
    assert isinstance(data["volunteer_id"], str)
    assert data["module"] in ("SAFETY_PROTOCOL", "LISTENING_SKILLS", "MANDATED_REPORTING", "CONFIDENTIALITY_BASICS")
    assert is_iso8601_timestamp(data["completed_at"])
    assert isinstance(data["valid_until"], str)
    assert data["status"] in ("VALID", "EXPIRED")


def assert_confidentiality_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["volunteer_id"], str)
    assert isinstance(data["policy_version"], str)
    assert "signed_at" in data
    assert isinstance(data["valid_until"], str)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "REVOKED", "EXPIRED")


def assert_call_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert data["weekday"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in ("ACTIVE", "PAUSED", "ARCHIVED")


def assert_call_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert "volunteer_id" in data
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["source"] in ("REGULAR", "MAKEUP", "ESCALATION_RETRY")
    assert "escalation_id" in data
    assert "rescheduled_from_id" in data
    assert data["status"] in ("SCHEDULED", "COMPLETED", "UNREACHED", "CANCELLED", "EXPIRED")
    assert "cancel_reason" in data


def assert_call_log(data: dict):
    _assert_common(data)
    assert isinstance(data["assignment_id"], str)
    assert is_iso8601_timestamp(data["called_at"])
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 0
    assert data["outcome"] in ("REACHED_OK", "REACHED_CONCERN", "NO_ANSWER", "BUSY", "REFUSED", "WRONG_NUMBER")
    assert data["concern_level"] in ("NONE", "ROUTINE", "URGENT", "IMMEDIATE_DANGER")
    assert isinstance(data["concern_categories"], list)
    assert isinstance(data["concern_flag"], bool)
    assert isinstance(data["follow_up_needed"], bool)
    assert isinstance(data["supervisor_notified"], bool)


def assert_escalation(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert data["trigger_type"] in ("NO_ANSWER_PROTOCOL", "CONCERN_IMMEDIATE", "MANUAL")
    assert data["stage"] in (
        "STEP_1_RETRY", "STEP_2_CONTACT", "STEP_3_WELFARE",
        "RESOLVED_OK", "RESOLVED_CONTACT_CONFIRMED", "RESOLVED_WITH_REFERRAL",
        "CLOSED_SUPERSEDED", "CLOSED_FALSE_ALARM",
    )
    assert isinstance(data["opened_by_user_id"], str)
    assert "opened_at" in data
    assert "stage_entered_at" in data
    assert "retry_assignment_id" in data
    assert "supersedes_escalation_id" in data
    assert isinstance(data["contact_attempts"], list)
    assert "resolution_note" in data


def assert_welfare_check(data: dict):
    _assert_common(data)
    assert isinstance(data["escalation_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["status"] in ("REQUESTED", "DISPATCHED", "COMPLETED", "DECLINED")
    assert data["disposition"] in ("NONE", "OK", "ASSIST_NEEDED", "NOT_FOUND")
    assert "requested_at" in data
    assert "dispatched_at" in data
    assert "completed_at" in data


def assert_service_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert "source_call_log_id" in data
    assert "escalation_id" in data
    assert data["service_type"] in ("MEALS", "TRANSPORT", "HOME_HEALTH", "ADULT_DAY", "CAREGIVER_SUPPORT", "BEHAVIORAL_HEALTH")
    assert data["priority"] in ("URGENT", "STANDARD", "ROUTINE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "DECLINED", "WITHDRAWN", "CLOSED")
    assert "submitted_at" in data
    assert "sla_due_at" in data
    assert isinstance(data["overdue"], bool)
    assert "decline_reason" in data


def assert_satisfaction_survey(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["period_month"], str)
    assert "issued_at" in data
    assert data["status"] in ("ISSUED", "SCORED", "EXPIRED")
    assert "survey_mean" in data


def assert_outcome_report(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["period_month"], str)
    assert data["status"] in ("PROVISIONAL", "FINALIZED")
    assert isinstance(data["calls_scheduled"], int)
    assert isinstance(data["calls_completed"], int)
    assert "completion_rate" in data
    assert isinstance(data["escalations_opened"], int)
    assert isinstance(data["escalations_resolved"], int)
    assert isinstance(data["referrals_submitted"], int)
    assert isinstance(data["unique_participants_reached"], int)
    assert "satisfaction_index" in data


def assert_capacity_invariants(program: dict):
    """Program capacity accounting invariants (PRD §2.8): occupied slots are
    participants in ENROLLED/SUSPENDED/WELFARE_HOLD and never negative."""
    assert program["occupied_slots"] >= 0, "occupied_slots must never be negative"
    assert program["occupied_slots"] <= program["total_capacity"], (
        f"occupied_slots {program['occupied_slots']} exceeds total_capacity {program['total_capacity']}"
    )
    assert program["waiting_count"] >= 0, "waiting_count must never be negative"
