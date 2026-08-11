"""Education sessions, completion capacity/uniqueness, venue conflicts, and
engagement-tier thresholds (PRD §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    create_education_session_payload, create_completion_payload,
    setup_active_program, setup_enrollment, add_enrollment,
    create_completed_session, record_completion, record_passed_completions,
    get_enrollment,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]
EDUCATOR = TEST_USERS["educator_headers"]


def test_cancel_completed_session_rejected(api):
    """PRD §3.6: "The educator then runs the session and either marks it
    completed — SCHEDULED to COMPLETED, after which completions may be
    recorded — or cancels it, SCHEDULED to CANCELLED. Either action on a
    session that is not SCHEDULED is rejected with
    `ERR_SESSION_NOT_SCHEDULED`."

    Design: Corner/state_machines/c_cancel_completed_session_rejected
    """
    ctx = setup_active_program()
    session = create_completed_session(ctx["program"]["id"])

    res = api.cancel_session(session["id"], EDUCATOR)
    validate_error(res, "ERR_SESSION_NOT_SCHEDULED")

    after = validate_success(api.get_education_session(session["id"], ADMIN), 200)
    assert after["status"] == "COMPLETED"


def test_duplicate_completion_rejected(api):
    """PRD §3.6: "each enrollment may be recorded against a given session only
    once, else `ERR_DUPLICATE_COMPLETION`."

    Design: Corner/errors/c_duplicate_completion_rejected
    """
    ctx = setup_enrollment()
    session = create_completed_session(ctx["program"]["id"])
    record_completion(session["id"], ctx["enrollment_id"])

    res = api.record_completion(
        session["id"],
        create_completion_payload(ctx["enrollment_id"], minutes_attended=30,
                                  passed=False),
        EDUCATOR)
    validate_error(res, "ERR_DUPLICATE_COMPLETION")


def test_session_full_rejected(api):
    """PRD §3.6: "The enrollment must be ACTIVE, else
    `ERR_ENROLLMENT_NOT_ACTIVE`; the session must still have room — when its
    recorded completions already equal its `capacity`, the write fails with
    `ERR_SESSION_FULL`; and each enrollment may be recorded against a given
    session only once, else `ERR_DUPLICATE_COMPLETION`."

    Design: Corner/errors/c_session_full_rejected
    """
    ctx = setup_enrollment(household_size=2, patient_name="Pat A")
    _, _, enrollment_b = add_enrollment(ctx, household_size=3,
                                        patient_name="Pat B")
    session = create_completed_session(ctx["program"]["id"], capacity=1)
    record_completion(session["id"], ctx["enrollment_id"])

    res = api.record_completion(
        session["id"], create_completion_payload(enrollment_b), EDUCATOR)
    validate_error(res, "ERR_SESSION_FULL")


# ---------------------------------------------------------------------------
# Depth instance: venue conflict with the thirty-minute buffer
# ---------------------------------------------------------------------------

def _program_with_session_a():
    """Active program with session A at venue RM-1, 2026-05-10 10:00-11:00."""
    ctx = setup_active_program()
    session_a = validate_success(api_client.create_education_session(
        ctx["program"]["id"],
        create_education_session_payload(
            topic="A", venue="RM-1", starts_at="2026-05-10T10:00:00Z",
            ends_at="2026-05-10T11:00:00Z"),
        EDUCATOR), 201)
    ctx["session_a"] = session_a
    return ctx


def test_venue_conflict_within_buffer_rejected(api):
    """PRD §3.6: "Venues are scarce within a program: a new session conflicts
    when its venue is already occupied by another session of the same program
    whose time window, extended by a thirty-minute buffer on each side,
    overlaps the new one, and the conflict is rejected with
    `ERR_VENUE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/education_session_venue_buffer_overlap
    """
    ctx = _program_with_session_a()
    # Session B starts 15 minutes after A ends: A's buffered window
    # (09:30-11:30) overlaps B's 11:15 start.
    res = api.create_education_session(
        ctx["program"]["id"],
        create_education_session_payload(
            topic="B", venue="RM-1", starts_at="2026-05-10T11:15:00Z",
            ends_at="2026-05-10T12:00:00Z"),
        EDUCATOR)
    validate_error(res, "ERR_VENUE_CONFLICT")


def test_venue_conflict_only_within_same_venue(api):
    """PRD §3.6: "Venues are scarce within a program: a new session conflicts
    when its venue is already occupied by another session of the same program
    whose time window, extended by a thirty-minute buffer on each side,
    overlaps the new one, and the conflict is rejected with
    `ERR_VENUE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/education_session_venue_buffer_overlap
    """
    ctx = _program_with_session_a()
    # Session D fully overlaps A in time but at a different venue: no conflict.
    session_d = validate_success(api.create_education_session(
        ctx["program"]["id"],
        create_education_session_payload(
            topic="D", venue="RM-2", starts_at="2026-05-10T10:30:00Z",
            ends_at="2026-05-10T11:00:00Z"),
        EDUCATOR), 201)
    assert session_d["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Depth instance: engagement-tier threshold boundary
# ---------------------------------------------------------------------------

def test_tier_stays_t1_below_threshold(api):
    """PRD §3.6: "If the count is at least the program's `tier3_completions`,
    the tier is T3; otherwise, if it is at least `tier2_completions`, the tier
    is T2; otherwise it remains T1. Reaching a threshold exactly promotes the
    enrollment."

    Design: Difficulty/boundary_precision_check/tier2_threshold_exact_completion_count
    """
    ctx = setup_enrollment()
    record_passed_completions(ctx, 2)  # 2 < tier2_completions (3)
    enrollment = get_enrollment(ctx["enrollment_id"])
    assert enrollment["engagement_tier"] == "T1"


def test_tier_promotes_at_exact_threshold(api):
    """PRD §3.6: "If the count is at least the program's `tier3_completions`,
    the tier is T3; otherwise, if it is at least `tier2_completions`, the tier
    is T2; otherwise it remains T1. Reaching a threshold exactly promotes the
    enrollment."

    Design: Difficulty/boundary_precision_check/tier2_threshold_exact_completion_count
    """
    ctx = setup_enrollment()
    sessions = record_passed_completions(ctx, 2)
    enrollment = get_enrollment(ctx["enrollment_id"])
    assert enrollment["engagement_tier"] == "T1"

    # The third passed completion reaches tier2_completions (3) exactly.
    record_passed_completions(ctx, 1, start_day=12)
    enrollment = get_enrollment(ctx["enrollment_id"])
    assert enrollment["engagement_tier"] == "T2"
