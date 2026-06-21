"""Shift and assignment state-machine transitions and precondition gates.

Covers Difficulty: non_linear_state_machine (shift FULLY_STAFFED<->OPEN cycle).
Covers Corner state_machines: post-already-posted, complete-before-end,
noshow-before-start, confirm-after-start, terminal-completed-cancel.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, make_worker_headers, set_clock, setup_location,
    setup_worker, setup_pay_period, create_posted_shift, create_draft_shift,
    assign_worker,
)


M = make_manager_headers()


def test_shift_bubbles_up_to_fully_staffed_on_last_seat(api):
    """PRD §2.10: "When an assignment enters the filled set and that makes the shift
    fully staffed, the shift auto-advances from OPEN to FULLY_STAFFED with no explicit
    request on the shift."

    A single-seat OPEN shift flips to FULLY_STAFFED when its one worker is assigned,
    and headcount_filled becomes 1.

    Design: Difficulty/non_linear_state_machine/shift_fully_staffed_reverts_to_open_on_cancel
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s["id"], worker["id"])
    shift = get_success_data(api.get_shift(s["id"], M))
    assert shift["status"] == "FULLY_STAFFED"
    assert shift["headcount_filled"] == 1


def test_shift_reverts_to_open_when_assignment_cancelled(api):
    """PRD §2.10: "When an assignment later leaves the filled set — through
    cancellation or a no-show — and the filled count drops below the required count,
    the shift reverts from FULLY_STAFFED back to OPEN so the seat can be re-staffed."

    Cancelling the only assignment on a FULLY_STAFFED single-seat shift drops
    headcount_filled to 0 and bubbles the shift back down to OPEN.

    Design: Difficulty/non_linear_state_machine/shift_fully_staffed_reverts_to_open_on_cancel
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    get_success_data(api.cancel_assignment(loc["id"], asg["id"], M))
    shift = get_success_data(api.get_shift(s["id"], M))
    assert shift["status"] == "OPEN"
    assert shift["headcount_filled"] == 0


def test_post_already_open_shift_rejected(api):
    """PRD §3.4: "Posting takes a shift from DRAFT to OPEN, making it eligible for
    bidding and assignment; it requires the shift to be in DRAFT (otherwise
    ERR_INVALID_SHIFT_STATE)."

    Posting a shift that is already OPEN (not DRAFT) -> ERR_INVALID_SHIFT_STATE.

    Design: Corner/state_machines/post_already_posted_shift_returns_invalid_shift_state
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=1)
    resp = api.post_shift(loc["id"], s["id"], M)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_STATE.value)


def test_complete_shift_before_end_rejected(api):
    """PRD §3.4: "Completing a shift is permitted only when it is OPEN or
    FULLY_STAFFED (otherwise ERR_INVALID_SHIFT_STATE) and only once the current clock
    instant has reached the shift's end_utc (otherwise ERR_SHIFT_NOT_ENDED)."

    Completing an OPEN shift while the clock is still before its end_utc ->
    ERR_SHIFT_NOT_ENDED.

    Design: Corner/state_machines/complete_shift_before_end_returns_shift_not_ended
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=1)
    resp = api.complete_shift(loc["id"], s["id"], M)
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_ENDED.value)


def test_noshow_before_shift_start_rejected(api):
    """PRD §3.6: "A manager marks a no-show on a worker who failed to appear,
    permitted only from SCHEDULED or CONFIRMED (otherwise
    ERR_INVALID_ASSIGNMENT_STATE) and only once the current clock instant has reached
    the shift's start_utc (otherwise ERR_SHIFT_NOT_STARTED)."

    Marking a no-show while the clock is still before the shift's start ->
    ERR_SHIFT_NOT_STARTED.

    Design: Corner/state_machines/noshow_before_shift_start_returns_shift_not_started
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    resp = api.no_show_assignment(loc["id"], asg["id"], M)
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_STARTED.value)


def test_confirm_after_shift_started_rejected(api):
    """PRD §3.5: "Confirmation is permitted only from SCHEDULED (otherwise
    ERR_INVALID_ASSIGNMENT_STATE), only by the owning worker whose worker_id equals
    X-User-ID (otherwise ERR_UNAUTHORIZED), and only while the current clock instant
    is still before the shift's start_utc (otherwise ERR_SHIFT_ALREADY_STARTED)."

    The owning worker confirming after the clock has reached the shift's start ->
    ERR_SHIFT_ALREADY_STARTED.

    Design: Corner/state_machines/confirm_after_shift_started_returns_shift_already_started
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    set_clock(api, "2026-06-05T09:00:01Z")
    resp = api.confirm_assignment(loc["id"], asg["id"], make_worker_headers(worker["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIFT_ALREADY_STARTED.value)


def test_cancel_completed_shift_rejected(api):
    """PRD §3.4: "Cancellation is permitted from any of DRAFT, OPEN, or FULLY_STAFFED
    (otherwise ERR_INVALID_SHIFT_STATE) and moves the shift to CANCELLED."

    A COMPLETED shift is terminal; attempting to cancel it -> ERR_INVALID_SHIFT_STATE.

    Design: Corner/state_machines/terminal_completed_shift_cannot_cancel
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api)
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=1)
    set_clock(api, "2026-06-02T13:00:01Z")
    get_success_data(api.complete_shift(loc["id"], s["id"], M))
    resp = api.cancel_shift(loc["id"], s["id"], M)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_STATE.value)
