"""Booking state machine: REQUESTED forks to CONFIRMED/REJECTED, transition gates,
terminal lockdown, no-show sweep, immediate consistency of the confirm response.

Covers Difficulty rule non_linear_state_machine (booking branch) and the
state_machines / consistency_model corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_member_headers,
    ApiErrorId,
    setup_member_ready,
    create_facility,
    create_lane,
    create_member,
    sign_waiver,
    top_up,
    request_booking,
    confirm_booking,
    create_confirmed_booking,
    run_completed_session,
    set_clock,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}
FRONT_DESK = {"X-User-ID": "test-frontdesk-1", "X-User-Role": "FrontDesk", "Content-Type": "application/json"}


# ─── non_linear_state_machine / booking_branch_requested_forks_confirm_vs_reject ─

def test_requested_forks_to_confirmed_and_rejected(api):
    """PRD §3.5: "A Member or FrontDesk operator confirms a REQUESTED booking, advancing
    it from REQUESTED to CONFIRMED". PRD §3.5: "A FacilityManager may instead reject a
    REQUESTED booking, moving it from REQUESTED to REJECTED; rejection applies no charge
    because charging happens only on confirmation".

    Design: Difficulty/non_linear_state_machine/booking_branch_requested_forks_confirm_vs_reject
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    bk_confirm = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    bk_reject = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T11:00:00Z", "2026-04-02T12:00:00Z",
    )
    confirm_booking(bk_confirm["id"], member["id"], lane["id"])
    rej = validate_success(api.reject_booking(bk_reject["id"], MANAGER), 200)

    confirmed = get_success_data(api.get_booking(bk_confirm["id"], MANAGER))
    assert confirmed["status"] == "CONFIRMED"
    assert rej["status"] == "REJECTED"


def test_reject_branch_leaves_wallet_charged_only_for_confirm(api):
    """PRD §3.5: "rejection applies no charge because charging happens only on
    confirmation, and the quote is simply discarded." PRD §3.5: "and that many tokens
    are subtracted from the member's token_balance."

    Design: Difficulty/non_linear_state_machine/booking_branch_requested_forks_confirm_vs_reject
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    bk_confirm = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    bk_reject = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T11:00:00Z", "2026-04-02T12:00:00Z",
    )
    confirm_booking(bk_confirm["id"], member["id"], lane["id"])
    validate_success(api.reject_booking(bk_reject["id"], MANAGER), 200)

    after = get_success_data(api.get_member(member["id"], MANAGER))
    # Off-peak 60-min 4000/hr -> 4000 cents -> ceil(4000/500)=8 tokens; only confirm debits.
    assert after["token_balance"] == 92


# ─── state_machines corner: reject_after_confirmed_invalid_state ───────────────

def test_reject_confirmed_booking_invalid_state(api):
    """PRD §3.5: "A FacilityManager may instead reject a REQUESTED booking, moving it
    from REQUESTED to REJECTED". PRD §2.11: "State validity is fifth: a target resource
    that is not in a legal state for the requested transition yields ERR_INVALID_STATE."

    Design: Corner/state_machines/reject_after_confirmed_invalid_state
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    booking = create_confirmed_booking(facility, lane, member)
    res = api.reject_booking(booking["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── state_machines corner: complete_from_confirmed_without_checkin_invalid_state ─

def test_complete_without_checkin_invalid_state(api):
    """PRD §3.6: "a FrontDesk operator completes a CHECKED_IN booking, advancing it from
    CHECKED_IN to COMPLETED". PRD §2.11: "a target resource that is not in a legal state
    for the requested transition yields ERR_INVALID_STATE."

    Design: Corner/state_machines/complete_from_confirmed_without_checkin_invalid_state
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    booking = create_confirmed_booking(facility, lane, member)
    res = api.complete_booking(booking["id"], FRONT_DESK)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── state_machines corner: booking_initial_state_requested ────────────────────

def test_new_booking_starts_requested(api):
    """PRD §3.4: "Requesting a booking does not charge, occupy, or confirm anything; it
    places the booking in REQUESTED status and stamps a provisional quoted_cost_cents
    using the forward-looking quote."

    Design: Corner/state_machines/booking_initial_state_requested
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "HOURLY",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    assert booking["status"] == "REQUESTED"


# ─── state_machines corner: cancel_completed_booking_terminal_lockdown ─────────

def test_cancel_completed_booking_invalid_state(api):
    """PRD §3.7: "A Member, a FrontDesk operator, or the system may cancel a booking that
    is in REQUESTED or CONFIRMED status, moving it to CANCELLED." PRD §2.11: "a target
    resource that is not in a legal state for the requested transition yields
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_completed_booking_terminal_lockdown
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    run_completed_session(
        facility, lane, member, "2026-04-01T09:00:00Z", "2026-04-01T10:00:00Z"
    )
    booking = get_success_data(
        api.list_bookings(MANAGER, params={"member_id": member["id"]})
    )
    # The single booking is now COMPLETED; cancel must be rejected.
    bk_id = booking[0]["id"] if isinstance(booking, list) else None
    assert bk_id is not None
    res = api.cancel_booking(bk_id, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── state_machines corner: no_show_sweep_via_run_ops_bubble_up_strike ─────────

def test_run_ops_sweeps_unattended_confirmed_to_no_show(api):
    """PRD §2.6: "every booking that is still CONFIRMED whose end instant is at or before
    the current clock and which was never checked in is transitioned to NO_SHOW".
    PRD §2.6: "The facility tracks a monotonic epoch_index ... increasing by exactly one
    each time an operator advances the epoch."

    Design: Corner/state_machines/no_show_sweep_via_run_ops_bubble_up_strike
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-01T09:00:00Z", end_utc="2026-04-01T10:00:00Z",
    )
    set_clock("2026-04-01T11:00:00Z")
    facility_after = validate_success(api.run_ops(facility["id"], MANAGER), 200)

    swept = get_success_data(api.get_booking(booking["id"], MANAGER))
    assert swept["status"] == "NO_SHOW"
    assert facility_after["epoch_index"] == 1


# ─── errors corner: no_show_sweep_marks_booking_no_show ────────────────────────

def test_no_show_sweep_marks_booking_no_show_state(api):
    """PRD §3.7: "any booking still CONFIRMED whose end_utc is at or before the current
    clock is transitioned from CONFIRMED to NO_SHOW; this increases the member's
    no_show_strikes by one".

    Design: Corner/errors/no_show_sweep_marks_booking_no_show
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=200)
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-01T09:00:00Z", end_utc="2026-04-01T10:00:00Z",
    )
    set_clock("2026-04-01T10:30:00Z")
    validate_success(api.run_ops(facility["id"], MANAGER), 200)
    swept = get_success_data(api.get_booking(booking["id"], MANAGER))
    assert swept["status"] == "NO_SHOW"


# ─── consistency_model corner: confirm_response_reflects_charge_immediately ─────

def test_confirm_response_carries_final_cost_and_debits_wallet(api):
    """PRD §3.5: "When the gates pass, confirmation computes final_cost_cents via the
    chronological charge." PRD §3.5: "and that many tokens are subtracted from the
    member's token_balance."

    Design: Corner/consistency_model/confirm_response_reflects_charge_immediately
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    confirmed = confirm_booking(booking["id"], member["id"], lane["id"])
    assert confirmed["final_cost_cents"] == 4000  # off-peak 60-min at 4000/hr

    member_after = get_success_data(api.get_member(member["id"], MANAGER))
    assert member_after["token_balance"] == 92  # 100 - ceil(4000/500)
