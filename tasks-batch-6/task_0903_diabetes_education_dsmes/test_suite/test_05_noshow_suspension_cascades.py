"""No-show suspension threshold, the suspend→cancel→reverse cascade, the
ACTIVE→SUSPENDED→ACTIVE cycle, and invalid session transitions.

Queue A (Difficulty): non_linear_state_machine (suspend/reinstate cycle),
transitive_cascade (depth-4), boundary_precision_check (no-show threshold).
Queue B (Corner): state_machines (cancel from cancelled).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]


# --- nl_enrollment_suspend_reinstate_cycle ---
def test_reinstate_returns_suspended_enrollment_to_active(api):
    """PRD §3.3: "Reinstatement returns a `SUSPENDED` enrollment to `ACTIVE`; it
    is valid only from `SUSPENDED` (else `ERR_ENROLLMENT_INVALID_STATE`),
    increments `version` by 1, and deliberately does not reset `no_show_count`".

    Three no-shows suspend the enrollment; reinstatement returns it to ACTIVE.

    Design: Difficulty/non_linear_state_machine/nl_enrollment_suspend_reinstate_cycle
    """
    ctx = setup_active_enrollment(api)
    th.suspend_via_no_shows(api, ctx, total_sessions=3, strikes=3, base_day="2026-05-09")
    reinstated = validate_success(api.reinstate_enrollment(ctx["enrollment_id"], COORD), 200)
    assert reinstated["status"] == "ACTIVE", \
        f"reinstated enrollment must be ACTIVE, got {reinstated['status']}"


def test_reinstate_retains_no_show_count(api):
    """PRD §3.3: "deliberately does not reset `no_show_count` — historical
    no-show strikes persist across a suspension so a reinstated patient remains
    one strike from re-suspension if already at the threshold."

    After reinstatement no_show_count stays at 3, not reset.

    Design: Difficulty/non_linear_state_machine/nl_enrollment_suspend_reinstate_cycle
    """
    ctx = setup_active_enrollment(api)
    th.suspend_via_no_shows(api, ctx, total_sessions=3, strikes=3, base_day="2026-05-09")
    reinstated = validate_success(api.reinstate_enrollment(ctx["enrollment_id"], COORD), 200)
    assert reinstated["no_show_count"] == 3, \
        f"no_show_count must persist at 3 after reinstate, got {reinstated['no_show_count']}"


# --- tc_no_show_suspend_cancel_reverse_depth4 ---
def test_third_no_show_suspends_enrollment(api):
    """PRD §3.6: "When `no_show_count` reaches the suspension threshold of 3 while
    the enrollment is `ACTIVE`, the enrollment automatically transitions from
    `ACTIVE` to `SUSPENDED`".

    Four sessions are scheduled; the third no-show tips the count to 3 and
    suspends the enrollment.

    Design: Difficulty/transitive_cascade/tc_no_show_suspend_cancel_reverse_depth4
    """
    ctx = setup_active_enrollment(api)
    th.suspend_via_no_shows(api, ctx, total_sessions=4, strikes=3, base_day="2026-05-13")
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["status"] == "SUSPENDED", f"enrollment must be SUSPENDED, got {enr['status']}"
    assert enr["no_show_count"] == 3, f"no_show_count must be 3, got {enr['no_show_count']}"


def test_suspension_cascade_cancels_remaining_and_reverses_hours(api):
    """PRD §3.6: "that suspension cascades by cancelling every remaining session
    of the enrollment still in `SCHEDULED` or `CHECKED_IN`, and each cascaded
    cancel reverses that session's provisional hours from `provisional_hours_used`
    and, for a group session, releases its class seat."

    The fourth, still-scheduled session is cancelled by the cascade and its hours
    reversed, leaving provisional_hours_used at 0.0.

    Design: Difficulty/transitive_cascade/tc_no_show_suspend_cancel_reverse_depth4
    """
    ctx = setup_active_enrollment(api)
    sessions = th.suspend_via_no_shows(api, ctx, total_sessions=4, strikes=3, base_day="2026-05-13")
    s4 = th.get_session(api, sessions[3]["id"])
    assert s4["encounter_status"] == "CANCELLED", \
        f"remaining session must be CANCELLED by cascade, got {s4['encounter_status']}"
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["provisional_hours_used"] == 0.0, \
        f"provisional_hours_used must be 0.0 after cascade, got {enr['provisional_hours_used']}"


# --- bp_no_show_threshold_boundary ---
def test_two_no_shows_leave_enrollment_active(api):
    """PRD §3.6: "When `no_show_count` reaches the suspension threshold of 3 while
    the enrollment is `ACTIVE`, the enrollment automatically transitions from
    `ACTIVE` to `SUSPENDED`".

    At count 2 (below the threshold) the enrollment stays ACTIVE.

    Design: Difficulty/boundary_precision_check/bp_no_show_threshold_boundary
    """
    ctx = setup_active_enrollment(api)
    th.suspend_via_no_shows(api, ctx, total_sessions=3, strikes=2, base_day="2026-05-18")
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["no_show_count"] == 2, f"no_show_count must be 2, got {enr['no_show_count']}"
    assert enr["status"] == "ACTIVE", f"at count 2 enrollment must stay ACTIVE, got {enr['status']}"


def test_third_no_show_crosses_threshold_to_suspended(api):
    """PRD §3.6: "When `no_show_count` reaches the suspension threshold of 3 while
    the enrollment is `ACTIVE`, the enrollment automatically transitions from
    `ACTIVE` to `SUSPENDED`".

    The 3rd no-show (>=3) flips the enrollment to SUSPENDED — boundary is >= on
    the count.

    Design: Difficulty/boundary_precision_check/bp_no_show_threshold_boundary
    """
    ctx = setup_active_enrollment(api)
    th.suspend_via_no_shows(api, ctx, total_sessions=3, strikes=3, base_day="2026-05-18")
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["no_show_count"] == 3, f"no_show_count must be 3, got {enr['no_show_count']}"
    assert enr["status"] == "SUSPENDED", f"at count 3 enrollment must be SUSPENDED, got {enr['status']}"


# --- Queue B: sm_session_cancel_from_cancelled_rejected ---
def test_cancel_already_cancelled_session_rejected(api):
    """PRD §3.6: "Every encounter transition is a dietitian action and requires
    the session to be in the correct originating state; any mismatch is rejected
    with `ERR_SESSION_INVALID_STATE`."

    Design: Corner/state_machines/sm_session_cancel_from_cancelled_rejected
    """
    ctx = setup_active_enrollment(api)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-23T09:00:00Z", "2026-05-23T10:00:00Z")
    th.cancel(api, ctx, sess["id"])
    resp = api.cancel_session(sess["id"], {}, ctx["diet"])
    validate_error(resp, ApiErrorId.ERR_SESSION_INVALID_STATE.value)
