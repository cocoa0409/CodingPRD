"""Session execution: completion & adverse vitals, missed/reschedule, void compensation.

Queue A (Difficulty): transitive_cascade (adverse hold), non_linear_state_machine
(missed/reschedule cycle), compensating_invariant (void conserves cap). Queue B
(Corner): adverse boundaries, consecutive-missed hold, invalid transitions.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_program_capacity_identity,
)
from test_helpers import fixtures as X


# ---------------------------------------------------------------------------
# Difficulty: adverse completion drives ON_HOLD and cancels scheduled sessions
# ---------------------------------------------------------------------------
def test_adverse_completion_holds_program_and_cancels_other_scheduled(api):
    """PRD §3.5: "If the completed session is adverse, the program is immediately
    driven from `ACTIVE` to `ON_HOLD`, which in turn cascades to cancel the program's
    remaining `SCHEDULED` sessions per §2.9."
    PRD §2.9: "every one of that program's sessions still in `SCHEDULED` status is
    transitioned to `CANCELLED`, releasing its station and clinician interval."

    Design: Difficulty/transitive_cascade/adverse_vitals_hold_cancels_scheduled
    """
    ctx = X.setup_active_program(api)
    s1 = X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    s2 = X.schedule_session(ctx, scheduled_start="2026-05-04T11:00:00Z", scheduled_end="2026-05-04T12:00:00Z")

    completed = X.complete_session(ctx, s1["id"], post_spo2=80, rpe=15, exercise_minutes=12)
    assert completed["status"] == "COMPLETED"
    assert completed["adverse_event"] is True

    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["status"] == "ON_HOLD"
    assert prog["sessions_used"] == 1

    s2_after = validate_success(api.get_session(s2["id"], ctx["coord"]))
    assert s2_after["status"] == "CANCELLED"


def test_adverse_completion_holds_program(api):
    """PRD §3.5: "The session is flagged adverse when the recorded post-exercise
    oxygen saturation is present and below 85 percent, or when the recorded rating of
    perceived exertion is present and at least 18."
    PRD §3.5: "If the completed session is adverse, the program is immediately driven
    from `ACTIVE` to `ON_HOLD`, which in turn cascades to cancel the program's remaining
    `SCHEDULED` sessions per §2.9."

    Design: Difficulty/transitive_cascade/adverse_vitals_hold_cancels_scheduled
    """
    ctx = X.setup_active_program(api)
    s1 = X.schedule_session(ctx)
    completed = X.complete_session(ctx, s1["id"], post_spo2=82, rpe=12, exercise_minutes=15)
    assert completed["adverse_event"] is True
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["status"] == "ON_HOLD"


# ---------------------------------------------------------------------------
# Difficulty: missed -> reschedule cycle
# ---------------------------------------------------------------------------
def test_missed_session_reschedule_returns_to_scheduled(api):
    """PRD §3.5: "When a patient does not show, the clinician marks the scheduled
    session as missed, moving it from `SCHEDULED` to `MISSED`; this increments the
    program's `consecutive_missed_count` and its `version`."
    PRD §3.5: "A `RehabCoordinator` may reschedule a missed session, moving it back
    from `MISSED` to `SCHEDULED` with a new `scheduled_start` and `scheduled_end` (and
    optionally a new `clinician_id` or `station_id`)."

    Design: Difficulty/non_linear_state_machine/session_missed_reschedule_cycle
    """
    ctx = X.setup_active_program(api)
    s = X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")

    missed = validate_success(api.mark_missed_session(s["id"], ctx["clin_headers"]))
    assert missed["status"] == "MISSED"

    new_start, new_end = "2026-05-06T09:00:00Z", "2026-05-06T10:00:00Z"
    rescheduled = validate_success(api.reschedule_session(
        s["id"], {"scheduled_start": new_start, "scheduled_end": new_end}, ctx["coord"]
    ))
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["scheduled_start"] == new_start


def test_reschedule_non_missed_session_rejected(api):
    """PRD §3.5: "Rescheduling is permitted only on a `MISSED` session (else
    `ERR_SESSION_NOT_MISSED`) and re-applies the same booking guards as initial
    scheduling."

    Design: Difficulty/non_linear_state_machine/session_missed_reschedule_cycle
    """
    ctx = X.setup_active_program(api)
    s = X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    resp = api.reschedule_session(
        s["id"], {"scheduled_start": "2026-05-06T09:00:00Z", "scheduled_end": "2026-05-06T10:00:00Z"}, ctx["coord"]
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_MISSED, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty: void completed session conserves the session cap
# ---------------------------------------------------------------------------
def test_void_completed_session_restores_capacity_cap5(api):
    """PRD §2.8: "Voiding a completed session decrements `sessions_used`, deliberately
    conserving the identity that `authorized_session_cap` equals `sessions_used` plus
    `sessions_remaining_authorized`."
    PRD §3.5: "Voiding decrements `sessions_used` by one and increments the program's
    `version`, reversing the accounting effect of the original completion."

    Design: Difficulty/compensating_invariant/void_completed_session_conserves_session_cap
    """
    ctx = X.setup_active_program(api, authorized_session_cap=5)
    s = X.schedule_session(ctx)
    X.complete_session(ctx, s["id"])
    before = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert before["sessions_used"] == 1
    assert before["sessions_remaining_authorized"] == 4
    assert_program_capacity_identity(before)

    voided = validate_success(api.void_session(s["id"], ctx["coord"]))
    assert voided["status"] == "VOIDED"
    after = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert after["sessions_used"] == 0
    assert after["sessions_remaining_authorized"] == 5
    assert_program_capacity_identity(after)


def test_void_completed_session_restores_capacity_cap3(api):
    """PRD §2.8: "Voiding a completed session decrements `sessions_used`, deliberately
    conserving the identity that `authorized_session_cap` equals `sessions_used` plus
    `sessions_remaining_authorized`."

    Design: Difficulty/compensating_invariant/void_completed_session_conserves_session_cap
    """
    ctx = X.setup_active_program(api, authorized_session_cap=3)
    s = X.schedule_session(ctx)
    X.complete_session(ctx, s["id"])
    before = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert before["sessions_used"] == 1
    assert before["sessions_remaining_authorized"] == 2

    validate_success(api.void_session(s["id"], ctx["coord"]))
    after = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert after["sessions_used"] == 0
    assert after["sessions_remaining_authorized"] == 3
    assert_program_capacity_identity(after)


# ---------------------------------------------------------------------------
# Corner: adverse-vitals boundaries
# ---------------------------------------------------------------------------
def test_adverse_vitals_spo2_85_boundary_not_adverse(api):
    """PRD §3.5: "The oxygen-saturation boundary is strict — a `post_spo2` of exactly
    85 is not adverse, while 84 is — whereas the exertion boundary is inclusive, so an
    `rpe` of 18 is adverse but 17 is not."

    Design: Corner/calculations/adverse_vitals_spo2_85_boundary_not_adverse
    """
    ctx = X.setup_active_program(api, program_type="PULMONARY")
    s = X.schedule_session(ctx)
    completed = X.complete_session(ctx, s["id"], post_spo2=85, rpe=14, exercise_minutes=25)
    assert completed["adverse_event"] is False
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["status"] == "ACTIVE"


def test_adverse_vitals_rpe_18_boundary_is_adverse(api):
    """PRD §3.5: "the exertion boundary is inclusive, so an `rpe` of 18 is adverse but
    17 is not."
    PRD §3.5: "If the completed session is adverse, the program is immediately driven
    from `ACTIVE` to `ON_HOLD`, which in turn cascades to cancel the program's remaining
    `SCHEDULED` sessions per §2.9."

    Design: Corner/calculations/adverse_vitals_rpe_18_boundary_is_adverse
    """
    ctx = X.setup_active_program(api)
    s = X.schedule_session(ctx)
    completed = X.complete_session(ctx, s["id"], post_spo2=94, rpe=18, exercise_minutes=20)
    assert completed["adverse_event"] is True
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["status"] == "ON_HOLD"


def test_three_consecutive_missed_sessions_hold_program(api):
    """PRD §3.5: "Three consecutive missed sessions signal disengagement: if
    `consecutive_missed_count` reaches 3 while the program is `ACTIVE`, the program is
    automatically moved from `ACTIVE` to `ON_HOLD`, again cascading to cancel remaining
    scheduled sessions."

    Design: Corner/cross_cutting_complexity_layers/three_consecutive_missed_sessions_hold_program
    """
    ctx = X.setup_active_program(api)
    s1 = X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    s2 = X.schedule_session(ctx, scheduled_start="2026-05-05T09:00:00Z", scheduled_end="2026-05-05T10:00:00Z")
    s3 = X.schedule_session(ctx, scheduled_start="2026-05-06T09:00:00Z", scheduled_end="2026-05-06T10:00:00Z")

    validate_success(api.mark_missed_session(s1["id"], ctx["clin_headers"]))
    validate_success(api.mark_missed_session(s2["id"], ctx["clin_headers"]))
    validate_success(api.mark_missed_session(s3["id"], ctx["clin_headers"]))

    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["consecutive_missed_count"] == 3
    assert prog["status"] == "ON_HOLD"


def test_complete_already_completed_session_rejected(api):
    """PRD §3.5: "Completion is allowed only when the session is `SCHEDULED` (else
    `ERR_SESSION_NOT_SCHEDULED`) and the parent program is `ACTIVE` (else
    `ERR_PROGRAM_NOT_ACTIVE`), moving the session from `SCHEDULED` to `COMPLETED`."

    Design: Corner/state_machines/complete_already_completed_session_returns_invalid_state
    """
    ctx = X.setup_active_program(api)
    s = X.schedule_session(ctx)
    X.complete_session(ctx, s["id"], post_spo2=95, rpe=12)
    resp = api.complete_session(s["id"], {"post_spo2": 96, "rpe": 11}, ctx["clin_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED, expected_status=409)
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["sessions_used"] == 1


def test_void_session_with_active_claim_blocked(api):
    """PRD §3.5: "Voiding is allowed only when the session is `COMPLETED` (else
    `ERR_SESSION_NOT_COMPLETED`) and no non-void billing claim references it (else
    `ERR_SESSION_HAS_ACTIVE_CLAIM`)."

    Design: Corner/cross_cutting_complexity_layers/void_session_with_active_claim_blocked
    """
    ctx = X.setup_active_program(api)
    s = X.create_completed_session(ctx)
    X.create_claim(ctx, s["id"])  # DRAFT claim, non-VOID
    resp = api.void_session(s["id"], ctx["coord"])
    validate_error(resp, ApiErrorId.ERR_SESSION_HAS_ACTIVE_CLAIM, expected_status=409)
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["sessions_used"] == 1
