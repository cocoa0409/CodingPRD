"""State machine behavior: the engagement ACTIVE<->PAUSED cycle, the check-in
SUBMITTED<->REVISION_REQUESTED cycle, and precondition / invalid-transition /
terminal-state enforcement.

Depth (queue A): non_linear_state_machine.
Breadth (queue B): state_machines precondition & terminal-state instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, api_client,
    set_clock, create_trainer, create_client, submit_intake,
    setup_subscription_engagement, setup_pack_engagement,
    create_pack, get_pack, book_pack_session, book_subscription_session,
    submit_check_in,
    make_trainer_headers, make_client_headers,
)


# ─── non_linear_state_machine / engagement_active_pause_resume_cycle ─────────

def test_engagement_pause_resume_pause_cycle(api):
    """PRD §3.2: "A trainer may manually pause an active engagement; doing so moves
    `status` from `ACTIVE` to `PAUSED` and sets `pause_reason` to `MANUAL`."
    PRD §3.2: "Resuming reverses the pause, moving `status` from `PAUSED` back to
    `ACTIVE` and resetting `pause_reason` to `NONE`."

    Pause -> resume -> pause loops back to PAUSED with pause_reason MANUAL,
    proving the ACTIVE<->PAUSED cycle is not a one-way pipeline.

    Design: Difficulty/non_linear_state_machine/engagement_active_pause_resume_cycle
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    th = make_trainer_headers(t_id)
    validate_success(api.pause_engagement(e_id, th))
    validate_success(api.resume_engagement(e_id, th))
    final = validate_success(api.pause_engagement(e_id, th))
    assert final["status"] == "PAUSED"
    assert final["pause_reason"] == "MANUAL"


def test_engagement_resume_resets_pause_reason_to_none(api):
    """PRD §3.2: "Resuming reverses the pause, moving `status` from `PAUSED` back to
    `ACTIVE` and resetting `pause_reason` to `NONE`."

    After a MANUAL pause, resume returns status to ACTIVE and pause_reason to NONE.

    Design: Difficulty/non_linear_state_machine/engagement_active_pause_resume_cycle
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    th = make_trainer_headers(t_id)
    validate_success(api.pause_engagement(e_id, th))
    resumed = validate_success(api.resume_engagement(e_id, th))
    assert resumed["status"] == "ACTIVE"
    assert resumed["pause_reason"] == "NONE"


# ─── non_linear_state_machine / checkin_submitted_revision_cycle ─────────────

def test_checkin_request_revision_then_resubmit_returns_to_submitted(api):
    """PRD §3.6: "The trainer may request a revision, moving `status` from
    `SUBMITTED` to `REVISION_REQUESTED`"
    PRD §3.6: "The client then resubmits, optionally supplying a corrected
    `weight_kg` and updated `photo_urls`, which moves `status` from
    `REVISION_REQUESTED` back to `SUBMITTED` and recomputes the `adherence_score`
    over the window"

    request-revision then resubmit loops the check-in back to SUBMITTED; with no
    habit logs the recomputed adherence_score is 0.

    Design: Difficulty/non_linear_state_machine/checkin_submitted_revision_cycle
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z",
                                        client_overrides={"sex": "FEMALE",
                                                          "birth_year": 1995,
                                                          "height_cm": 165})
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    ci = submit_check_in(c_id, e_id, "2026-06-01T08:00:00Z", 64,
                         "2026-05-25T00:00:00Z", "2026-06-01T00:00:00Z")
    validate_success(api.request_revision(ci["id"], make_trainer_headers(t_id)))
    resubmitted = validate_success(
        api.resubmit_check_in(ci["id"], {"weight_kg": 63}, make_client_headers(c_id)))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["adherence_score"] == 0


def test_checkin_request_revision_sets_revision_requested(api):
    """PRD §3.6: "The trainer may request a revision, moving `status` from
    `SUBMITTED` to `REVISION_REQUESTED`; this requires the check-in to be
    `SUBMITTED`, otherwise `ERR_INVALID_STATE`."

    request-revision moves a SUBMITTED check-in to REVISION_REQUESTED (first leg of
    the cycle, on a distinct entity from the engagement cycle).

    Design: Difficulty/non_linear_state_machine/checkin_submitted_revision_cycle
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z",
                                        client_overrides={"sex": "FEMALE",
                                                          "birth_year": 1995,
                                                          "height_cm": 165})
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    ci = submit_check_in(c_id, e_id, "2026-06-01T08:00:00Z", 64,
                         "2026-05-25T00:00:00Z", "2026-06-01T00:00:00Z")
    revised = validate_success(api.request_revision(ci["id"], make_trainer_headers(t_id)))
    assert revised["status"] == "REVISION_REQUESTED"


# ─── Corner: state_machines / assess_client_not_submitted_returns_invalid ────

def test_assess_draft_client_returns_intake_not_submitted(api):
    """PRD §3.1: "Accepting it advances `intake_status` from `SUBMITTED` to
    `ASSESSED` ... this transition requires the record to be in `SUBMITTED` and
    otherwise raises `ERR_INTAKE_NOT_SUBMITTED`."

    Assessing a DRAFT (never-submitted) client returns ERR_INTAKE_NOT_SUBMITTED and
    leaves intake_status DRAFT.

    Design: Corner/state_machines/assess_client_not_submitted_returns_invalid
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    client = create_client(t_id)
    resp = api.assess_client(client["id"], make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_SUBMITTED.value)
    refreshed = validate_success(api.get_client(client["id"], make_trainer_headers(t_id)))
    assert refreshed["intake_status"] == "DRAFT"


# ─── Corner: state_machines / complete_booking_before_start_returns_not_started ─

def test_complete_booking_before_start_returns_not_started(api):
    """PRD §3.5: "A booking is **completed** by the trainer, moving `status` from
    `BOOKED` to `COMPLETED`; this requires the booking to be `BOOKED` (otherwise
    `ERR_INVALID_STATE`) and requires that the logical clock has reached or passed
    the booking's `start_utc` (otherwise `ERR_SESSION_NOT_STARTED`)."

    Completing a future booking (clock before start) returns ERR_SESSION_NOT_STARTED
    and leaves it BOOKED.

    Design: Corner/state_machines/complete_booking_before_start_returns_not_started
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-20T10:00:00Z", "2026-06-20T11:00:00Z")
    resp = api.complete_booking(b["id"], make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STARTED.value)
    refreshed = validate_success(api.get_booking(b["id"], make_trainer_headers(t_id)))
    assert refreshed["status"] == "BOOKED"


# ─── Corner: state_machines / mark_no_show_before_end_returns_not_ended ───────

def test_mark_no_show_before_end_returns_not_ended(api):
    """PRD §3.5: "This moves `status` from `BOOKED` to `NO_SHOW`, requires the
    booking to be `BOOKED` (otherwise `ERR_INVALID_STATE`), and requires that the
    logical clock has reached or passed the booking's `end_utc` (otherwise
    `ERR_SESSION_NOT_ENDED`)."

    mark-no-show with the clock between start and end returns ERR_SESSION_NOT_ENDED
    and leaves the booking BOOKED.

    Design: Corner/state_machines/mark_no_show_before_end_returns_not_ended
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-05T10:00:00Z", "2026-06-05T11:00:00Z")
    set_clock("2026-06-05T10:30:00Z")
    resp = api.mark_no_show(b["id"], make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_ENDED.value)
    refreshed = validate_success(api.get_booking(b["id"], make_trainer_headers(t_id)))
    assert refreshed["status"] == "BOOKED"


# ─── Corner: state_machines / cancel_already_cancelled_booking_invalid_state ──

def test_cancel_already_cancelled_booking_returns_invalid_state(api):
    """PRD §3.5: "Cancelling requires the booking to be `BOOKED`, otherwise
    `ERR_INVALID_STATE`."

    Cancelling an already-CANCELLED booking returns ERR_INVALID_STATE; no double
    seat release (sessions_remaining stays 5).

    Design: Corner/state_machines/cancel_already_cancelled_booking_invalid_state
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-20T10:00:00Z", "2026-06-20T11:00:00Z")
    validate_success(api.cancel_booking(b["id"], make_client_headers(c_id)))
    resp = api.cancel_booking(b["id"], make_client_headers(c_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["sessions_remaining"] == 5


# ─── Corner: state_machines / reschedule_within_24h_returns_too_late ─────────

def test_reschedule_within_24h_returns_too_late(api):
    """PRD §3.5: "Rescheduling requires the booking to be `BOOKED` (otherwise
    `ERR_INVALID_STATE`) and, like a free cancellation, requires that the move is
    made at least twenty-four hours ahead — the gap from the logical clock to the
    original `start_utc` must be at least 86,400 seconds, or the request is
    rejected with `ERR_RESCHEDULE_TOO_LATE`."

    A booking starting 12h away cannot be rescheduled; status stays BOOKED.

    Design: Corner/state_machines/reschedule_within_24h_returns_too_late
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-05T00:00:00Z",
                                        cycle_start_utc="2026-06-05T00:00:00Z")
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    b = book_subscription_session(t_id, e_id, "2026-06-05T12:00:00Z",
                                  "2026-06-05T13:00:00Z", as_client_id=c_id)
    resp = api.reschedule_booking(b["id"],
                                  {"start_utc": "2026-06-10T12:00:00Z",
                                   "end_utc": "2026-06-10T13:00:00Z"},
                                  make_client_headers(c_id))
    validate_error(resp, ApiErrorId.ERR_RESCHEDULE_TOO_LATE.value)
    refreshed = validate_success(api.get_booking(b["id"], make_client_headers(c_id)))
    assert refreshed["status"] == "BOOKED"


# ─── Corner: state_machines / resume_active_engagement_invalid_state ─────────

def test_resume_active_engagement_returns_invalid_state(api):
    """PRD §3.2: "Resume requires the engagement to be `PAUSED`, raising
    `ERR_INVALID_STATE` otherwise."

    Resuming a never-paused ACTIVE engagement returns ERR_INVALID_STATE.

    Design: Corner/state_machines/resume_active_engagement_invalid_state
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    resp = api.resume_engagement(e_id, make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner: state_machines / terminal_ended_engagement_rejects_pause ────────

def test_pause_ended_engagement_returns_invalid_state(api):
    """PRD §3.2: "Either way, pausing requires the engagement to be `ACTIVE` and
    otherwise raises `ERR_INVALID_STATE`"

    Pausing an ENDED (terminal) engagement returns ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_ended_engagement_rejects_pause
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    th = make_trainer_headers(t_id)
    validate_success(api.end_engagement(e_id, th))
    resp = api.pause_engagement(e_id, th)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
