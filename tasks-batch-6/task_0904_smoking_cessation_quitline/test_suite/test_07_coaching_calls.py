"""Coaching-call scheduling: buffer conflicts, language gate, active gate, lead time."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    setup_active_enrollment_with_coach, setup_pending_enrollment,
    setup_active_enrollment, set_clock, create_coach,
)
from test_helpers import factories as F

CM = TEST_USERS["case_manager_headers"]


def _schedule(api, enrollment_id, coach_id, start, minutes=30):
    return api.create_coaching_call(
        enrollment_id,
        F.create_coaching_call_payload(
            coach_id=coach_id, scheduled_start=start, duration_minutes=minutes
        ),
        CM,
    )


def test_coach_double_booked_within_buffer(api):
    """PRD §2.6: "if the requested interval overlaps an existing one, or the gap
    between the two intervals is strictly less than fifteen minutes, the request is
    rejected with `ERR_COACH_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/coach_double_booked_within_buffer
    """
    ctx = setup_active_enrollment_with_coach(api, coach_languages=["EN"], cpd=10)
    validate_success(_schedule(api, ctx["enrollment_id"], ctx["coach_id"], "2026-06-02T10:00:00Z"), 201)
    # First call occupies [10:00, 10:30); a second at 10:40 leaves only a 10-min gap (< 15).
    resp = _schedule(api, ctx["enrollment_id"], ctx["coach_id"], "2026-06-02T10:40:00Z")
    validate_error(resp, ApiErrorId.ERR_COACH_DOUBLE_BOOKED.value)


def test_coach_gap_exactly_buffer_accepted(api):
    """PRD §2.6: "every pair of a coach's calls must be separated by at least
    `COACH_BUFFER_MINUTES` — fifteen minutes — of clearance."

    Design: Difficulty/resource_temporal_overlap/coach_double_booked_within_buffer
    """
    ctx = setup_active_enrollment_with_coach(api, coach_languages=["EN"], cpd=10)
    validate_success(_schedule(api, ctx["enrollment_id"], ctx["coach_id"], "2026-06-02T10:00:00Z"), 201)
    # Second call at 10:45 leaves exactly a 15-min gap after [10:00, 10:30) -> allowed.
    data = validate_success(
        _schedule(api, ctx["enrollment_id"], ctx["coach_id"], "2026-06-02T10:45:00Z"), 201
    )
    assert data["status"] == "SCHEDULED"


def test_schedule_call_requires_active_enrollment_pending(api):
    """PRD §2.5: "State admissibility — the target resource is in a state that admits
    the requested transition, and enrollment-scoped operations require the enrollment
    to be `ACTIVE`, else `ERR_INVALID_STATE` or `ERR_ENROLLMENT_NOT_ACTIVE` (409)."

    Design: Difficulty/cross_entity_state_dependency/coaching_call_create_requires_enrollment_active
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    coach = create_coach(api, languages=["EN"])
    ctx = setup_pending_enrollment(api, cpd=10)
    resp = _schedule(api, ctx["enrollment_id"], coach["id"], "2026-06-02T10:00:00Z")
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_schedule_call_requires_active_enrollment_disenrolled(api):
    """PRD §2.5: "State admissibility — the target resource is in a state that admits
    the requested transition, and enrollment-scoped operations require the enrollment
    to be `ACTIVE`, else `ERR_INVALID_STATE` or `ERR_ENROLLMENT_NOT_ACTIVE` (409)."

    Design: Difficulty/cross_entity_state_dependency/coaching_call_create_requires_enrollment_active
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    coach = create_coach(api, languages=["EN"])
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False)
    validate_success(api.disenroll_enrollment(ctx["enrollment_id"], CM))
    resp = _schedule(api, ctx["enrollment_id"], coach["id"], "2026-06-02T10:00:00Z")
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_referential_language_gate_beats_temporal_past_slot(api):
    """PRD §2.5: "6. **Referential legality** — cross-entity reference rules such as
    coach-language compatibility, an existing committed quit attempt for NRT approval,
    and the sponsor program not being closed, else `ERR_COACH_LANGUAGE_MISMATCH`,
    `ERR_NO_COMMITTED_QUIT_ATTEMPT`, or `ERR_PROGRAM_CLOSED` (409)."
    PRD §2.5: "7. **Temporal legality** — scheduling lead time and coach buffering,
    NRT course-interval non-overlap, and follow-up window openness, else
    `ERR_SCHEDULE_WINDOW_INVALID`, `ERR_COACH_DOUBLE_BOOKED`, `ERR_NRT_COURSE_OVERLAP`,
    or `ERR_FOLLOWUP_WINDOW_NOT_OPEN` (409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_schedule_call
    """
    ctx = setup_active_enrollment_with_coach(
        api, coach_languages=["ES"], participant_language="EN", cpd=10
    )
    # Coach speaks only ES (mismatch) AND slot is in the past (window invalid).
    resp = _schedule(api, ctx["enrollment_id"], ctx["coach_id"], "2026-05-01T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_COACH_LANGUAGE_MISMATCH.value)


def test_language_mismatch_reported_even_with_valid_slot(api):
    """PRD §3.5: "the chosen coach's `languages` must contain the participant's
    `primary_language`, else the request is rejected with
    `ERR_COACH_LANGUAGE_MISMATCH`".

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_schedule_call
    """
    ctx = setup_active_enrollment_with_coach(
        api, coach_languages=["ES"], participant_language="EN", cpd=10
    )
    # Valid future slot; only the language gate can fail.
    resp = _schedule(api, ctx["enrollment_id"], ctx["coach_id"], "2026-06-02T10:00:00Z")
    validate_error(resp, ApiErrorId.ERR_COACH_LANGUAGE_MISMATCH.value)


def test_schedule_window_invalid_past_slot(api):
    """PRD §2.6: "a call's `scheduled_start` must be at least
    `SCHEDULE_MIN_LEAD_MINUTES` — sixty minutes — after the current clock time; a
    start in the past or inside that one-hour lead window is rejected with
    `ERR_SCHEDULE_WINDOW_INVALID`."

    Design: Corner/validations/schedule_window_invalid_past_slot
    """
    ctx = setup_active_enrollment_with_coach(api, coach_languages=["EN"], cpd=10)
    resp = _schedule(api, ctx["enrollment_id"], ctx["coach_id"], "2026-05-01T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_INVALID.value)


def test_schedule_call_unknown_coach_returns_not_found(api):
    """PRD §2.5: "The first identifier that does not correspond to an existing
    resource halts processing with that resource's specific not-found error —
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_EMPLOYER_PROGRAM_NOT_FOUND`, `ERR_COACH_NOT_FOUND`,
    `ERR_QUIT_ATTEMPT_NOT_FOUND`, `ERR_COACHING_CALL_NOT_FOUND`, or
    `ERR_NRT_SHIPMENT_NOT_FOUND` — before any deeper resource or business rule is
    consulted."

    Design: Corner/endpoints/schedule_call_with_unknown_coach_returns_not_found
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False, clock="2026-06-01T00:00:00Z")
    resp = _schedule(api, ctx["enrollment_id"], NON_EXISTENT_UUID, "2026-06-02T10:00:00Z")
    validate_error(resp, ApiErrorId.ERR_COACH_NOT_FOUND.value)
