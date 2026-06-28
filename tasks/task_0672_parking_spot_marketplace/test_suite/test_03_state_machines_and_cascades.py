"""Booking parallel dimensions, transfer-offer branching, and cascade chains.

Covers the non-linear state machine instances (parallel occupancy/settlement axes,
transfer-offer branching) and the transitive cascade chains (suspension auto-cancel,
overstay auto-log), plus the corner-design state-machine transition instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_driver_headers, make_host_headers, TEST_USERS,
    setup_host_driver_spot, setup_reserved_booking, setup_checked_in_booking,
    setup_pending_transfer_offer, setup_suspended_driver, checkout_at, set_clock,
    create_booking, log_violation, confirm_violation, mark_no_show, register_driver,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: non_linear_state_machine / booking_parallel_dimensions ───

def test_booking_occupancy_and_settlement_advance_independently(api):
    """PRD §3.4: "A booking begins `RESERVED` and `UNSETTLED`, but on a successful
    confirmation charge its `settlement_status` is set to `SETTLED`".
    PRD §3.5: "The checkout then advances `occupancy_status` from `CHECKED_IN` to
    `CHECKED_OUT` while `settlement_status` stays `SETTLED` (only the occupancy dimension
    moves)".

    A booking checked in and out on time ends CHECKED_OUT while settlement stays SETTLED:
    the two axes move on different triggers.

    Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_occupancy_vs_settlement
    """
    host, driver, spot, booking = setup_checked_in_booking(
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T11:00:00Z",
        spot_overrides={"overstay_grace_minutes": 15})
    assert booking["occupancy_status"] == "CHECKED_IN"
    assert booking["settlement_status"] == "SETTLED"

    out = checkout_at(driver["id"], booking["id"], "2026-04-08T11:00:00Z")
    assert out["occupancy_status"] == "CHECKED_OUT"
    assert out["settlement_status"] == "SETTLED"


def test_settlement_settled_at_creation_before_occupancy_advances(api):
    """PRD §3.5: "When a booking is created, the freshly computed `quoted_amount_cents` is
    charged against the driver's wallet: the driver's `wallet_balance_cents` is debited by
    that amount, the booking's `settlement_status` is set to `SETTLED`".
    PRD §3.3: "`occupancy_status` starts at `RESERVED`".

    A freshly created booking is RESERVED yet already SETTLED — the settlement axis reached
    its terminal-for-this-path value while occupancy is still at its initial state.

    Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_occupancy_vs_settlement
    """
    host, driver, spot, booking = setup_reserved_booking(
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T11:00:00Z",
        clock="2026-04-08T09:00:00Z")
    assert booking["occupancy_status"] == "RESERVED"
    assert booking["settlement_status"] == "SETTLED"


# ─── Difficulty: non_linear_state_machine / transfer_offer_branching ───

def test_transfer_offer_decline_branch_no_reassignment(api):
    """PRD §3.9: "The recipient may instead decline a pending offer, advancing its `status`
    from `PENDING` to `DECLINED` and incrementing its `version`".

    Declining drives PENDING->DECLINED and leaves the booking's driver_id with the original
    holder — a divergent branch from accept (which reassigns).

    Design: Difficulty/non_linear_state_machine/transfer_offer_branching_pending_to_three_terminals
    """
    host, da, db, spot, booking, offer = setup_pending_transfer_offer()
    declined = get_success_data(api.decline_transfer_offer(offer["id"], make_driver_headers(db["id"])))
    assert declined["status"] == "DECLINED"
    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(da["id"])))
    assert b["driver_id"] == da["id"], "decline must not reassign the booking"


def test_transfer_offer_withdraw_branch_terminal(api):
    """PRD §3.9: "The original offeror may withdraw a pending offer they made, advancing its
    `status` from `PENDING` to `WITHDRAWN` and incrementing its `version`; withdrawing
    requires the acting driver to be the offeror".

    Withdrawing by the offeror drives PENDING->WITHDRAWN — a third distinct terminal from
    accept/decline.

    Design: Difficulty/non_linear_state_machine/transfer_offer_branching_pending_to_three_terminals
    """
    host, da, db, spot, booking, offer = setup_pending_transfer_offer()
    withdrawn = get_success_data(api.withdraw_transfer_offer(offer["id"], make_driver_headers(da["id"])))
    assert withdrawn["status"] == "WITHDRAWN"
    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(da["id"])))
    assert b["driver_id"] == da["id"]


# ─── Difficulty: transitive_cascade / confirm_violation_suspends_driver_autocancels ───

def test_confirm_suspension_autocancels_reserved_and_refunds(api):
    """PRD §3.8: "When the recomputed tier becomes `SUSPENDED`, a further cascade
    auto-cancels every booking held by that driver whose `occupancy_status` is still
    `RESERVED`: each such booking has its `occupancy_status` set to `CANCELLED` and its
    `settlement_status` set to `REFUNDED`, and the tiered refund of §3.6 is credited to that
    driver's `wallet_balance_cents`."
    PRD §3.8: "the tier is `SUSPENDED` when `violation_points` is at least 10".

    A NO_SHOW (w=3) base 4 with no priors assesses 12 >= 10 -> SUSPENDED; the driver's
    still-RESERVED booking (quoted 800, lead > 7 days so full refund) auto-cancels to
    CANCELLED/REFUNDED and the full 800 is credited back, restoring the wallet to 5000.

    Design: Difficulty/transitive_cascade/confirm_violation_suspends_driver_autocancels_and_refunds_depth4
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=5000,
                                                spot_overrides={"zone_code": "Z7",
                                                                "availability_end": "2026-06-01T00:00:00Z"})
    set_clock("2026-04-08T09:00:00Z")
    # The booking that gets auto-cancelled (lead > 7 days from clock).
    # 2h HOURLY at base 400 on a Monday (no surge/weekend) -> quoted 800.
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T12:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 800
    vr = log_violation(host["id"], booking["id"], "NO_SHOW", 4)
    confirmed = confirm_violation(vr["id"])
    assert confirmed["assessed_points"] == 12, confirmed["assessed_points"]

    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["violation_points"] == 12
    assert drv["standing_tier"] == "SUSPENDED"
    assert drv["wallet_balance_cents"] == 5000, drv["wallet_balance_cents"]

    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(driver["id"])))
    assert b["occupancy_status"] == "CANCELLED"
    assert b["settlement_status"] == "REFUNDED"


def test_confirm_suspension_sets_tier_suspended(api):
    """PRD §3.8: "Confirming a record adds its `assessed_points` to the driver's
    `violation_points`, which recomputes the driver's `standing_tier`".

    Confirming a NO_SHOW base 4 (assessed 12) drives the driver to SUSPENDED.

    Design: Difficulty/transitive_cascade/confirm_violation_suspends_driver_autocancels_and_refunds_depth4
    """
    host, driver, spot, booking, vr = setup_suspended_driver(no_show_base_points=4)
    assert vr["assessed_points"] == 12
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["standing_tier"] == "SUSPENDED"


# ─── Difficulty: transitive_cascade / checkout_overstay_autologs_violation ───

def test_checkout_overstay_autologs_violation_raises_provisional(api):
    """PRD §3.5: "One further cascade applies when the actual checkout instant is later than
    `end_at` plus grace: the checkout auto-logs a `ViolationRecord` against the booking with
    `violation_kind` of `OVERSTAY`, `status` of `OPEN`, and `base_points` of 1".
    PRD §3.5: "That record's creation re-derives the driver's `provisional_violation_points`,
    which on this path increases by 1 (the `OVERSTAY` weight of 1 multiplied by the proposed
    `base_points` of 1, with no escalation while open)".

    Booking [10:00,11:00) base 400 quoted 400, checkout at 12:30 (overstay): overstay 75 min
    -> ceil 2h -> 2*400*1.5 = 1200, final = 400+1200 = 1600; provisional points rise to 1.

    Design: Difficulty/transitive_cascade/checkout_overstay_autologs_violation_sets_provisional_depth3
    """
    host, driver, spot, booking = setup_checked_in_booking(
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T11:00:00Z",
        spot_overrides={"base_hourly_cents": 400, "overstay_grace_minutes": 15})
    out = checkout_at(driver["id"], booking["id"], "2026-04-08T12:30:00Z")
    assert out["final_amount_cents"] == 1600, out["final_amount_cents"]
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["provisional_violation_points"] == 1, drv["provisional_violation_points"]


def test_checkout_overstay_final_includes_overstay_charge(api):
    """PRD §3.5: "the overstay seconds are divided by 3600 and rounded up to a whole number
    of overstay hours, and the overstay charge is those hours multiplied by the spot's
    `base_hourly_cents` multiplied by 15000 basis points divided by 10000".

    Booking [10:00,11:00) base 400, checkout 12:30 -> overstay 75 min -> ceil 2h ->
    2*400*1.5 = 1200; final = 400 base + 1200 = 1600.

    Design: Difficulty/transitive_cascade/checkout_overstay_autologs_violation_sets_provisional_depth3
    """
    host, driver, spot, booking = setup_checked_in_booking(
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T11:00:00Z",
        spot_overrides={"base_hourly_cents": 400, "overstay_grace_minutes": 15})
    out = checkout_at(driver["id"], booking["id"], "2026-04-08T12:30:00Z")
    assert out["final_amount_cents"] == 1600


# ─── Corner: state_machines ──────────────────────────────────────────────────

def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §3.6: "Cancellation requires the acting driver to hold the booking and the
    booking to be currently `RESERVED`; otherwise it is rejected with `ERR_INVALID_STATE`."

    A booking already CANCELLED rejects a second cancel with ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_already_cancelled_booking_returns_invalid_state
    """
    host, driver, spot, booking = setup_reserved_booking(clock="2026-04-08T09:00:00Z")
    get_success_data(api.cancel_booking(booking["id"], make_driver_headers(driver["id"])))
    res = api.cancel_booking(booking["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_checkout_from_reserved_returns_invalid_state(api):
    """PRD §3.5: "Checkout requires the acting driver to hold the booking and the booking to
    be currently `CHECKED_IN`; otherwise the state check fails with `ERR_INVALID_STATE`."

    Checking out a RESERVED (never checked-in) booking returns ERR_INVALID_STATE.

    Design: Corner/state_machines/checkout_from_reserved_without_checkin_returns_invalid_state
    """
    host, driver, spot, booking = setup_reserved_booking()
    res = api.check_out_booking(booking["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_checkin_before_start_returns_window_closed(api):
    """PRD §3.4: "A check-in attempted before `start_at`, or once the window plus grace has
    fully elapsed, is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409)".

    Booking [10:00,11:00); a check-in at 09:00 (strictly before start_at) is rejected with
    ERR_CHECKIN_WINDOW_CLOSED (lower-edge boundary).

    Design: Corner/state_machines/checkin_before_start_returns_window_closed
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "ZSM3"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    # Clock is still 09:00, strictly before start_at.
    res = api.check_in_booking(booking["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_CHECKIN_WINDOW_CLOSED")


def test_mark_no_show_before_expiry_returns_invalid_state(api):
    """PRD §3.4: "This is driven by the platform administrator, or by the server during a
    clock advance, once the logical clock reaches or passes `end_at` plus the spot's
    `overstay_grace_minutes` while the booking is still `RESERVED`."

    mark-no-show at 10:30 (before end+grace = 11:15) returns ERR_INVALID_STATE.

    Design: Corner/state_machines/mark_no_show_before_expiry_returns_invalid_state
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "ZSM4"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    set_clock("2026-04-08T10:30:00Z")
    res = api.mark_no_show(booking["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_relisted_spot_accepts_booking(api):
    """PRD §3.2: "The host may relist an `UNLISTED` spot, transitioning `listing_status`
    back from `UNLISTED` to `LISTED`."
    PRD §3.3: "The spot's `listing_status` must be `LISTED`; booking an `UNLISTED` spot is
    rejected with `ERR_SPOT_UNLISTED`".

    A spot listed -> unlisted -> relisted accepts a booking again (occupancy RESERVED),
    proving the cycle re-enables bookings.

    Design: Corner/state_machines/relisted_spot_accepts_booking_cyclic
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"zone_code": "ZSM5"})
    get_success_data(api.unlist_spot(spot["id"], make_host_headers(host["id"])))
    relisted = get_success_data(api.relist_spot(spot["id"], make_host_headers(host["id"])))
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", relisted["version"])
    assert booking["occupancy_status"] == "RESERVED"


def test_unlist_spot_with_active_booking_rejected(api):
    """PRD §3.2: "The owning host may unlist a LISTED spot ... but only when no booking on
    that spot is currently in `RESERVED` or `CHECKED_IN` occupancy — an attempt while an
    active reservation exists ... an invalid current state surfaces as `ERR_INVALID_STATE`."

    Unlisting a spot that has a RESERVED booking returns ERR_INVALID_STATE.

    Design: Corner/state_machines/unlist_spot_with_active_booking_rejected
    """
    host, driver, spot, booking = setup_reserved_booking(spot_overrides={"zone_code": "ZSM6"})
    res = api.unlist_spot(spot["id"], make_host_headers(host["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_confirm_already_confirmed_violation_returns_invalid_state(api):
    """PRD §3.8: "Confirming a record requires it to be `OPEN`".

    Confirming a record already CONFIRMED returns ERR_INVALID_STATE and the driver's
    confirmed points are not added a second time.

    Design: Corner/state_machines/confirm_already_confirmed_violation_returns_invalid_state
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"zone_code": "ZSM7"})
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-20T10:00:00Z", "2026-04-20T11:00:00Z", spot["version"])
    vr = log_violation(host["id"], booking["id"], "OVERSTAY", 4)
    confirm_violation(vr["id"])
    res = api.confirm_violation(vr["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
    drv = get_success_data(api.get_driver(driver["id"], make_driver_headers(driver["id"])))
    assert drv["violation_points"] == 4, drv["violation_points"]


def test_cancel_reserved_withdraws_pending_offer(api):
    """PRD §3.6: "cancelling a `RESERVED` booking that has a `PENDING` transfer offer
    auto-withdraws that offer by setting its `status` to `WITHDRAWN`, which makes the offer
    terminal so that no later accept or decline is possible on it."

    Cancelling a RESERVED booking with a PENDING offer drives the offer to WITHDRAWN and the
    booking to CANCELLED.

    Design: Corner/state_machines/cancel_reserved_booking_withdraws_pending_offer_cascade
    """
    host, da, db, spot, booking, offer = setup_pending_transfer_offer()
    get_success_data(api.cancel_booking(booking["id"], make_driver_headers(da["id"])))
    off = get_success_data(api.get_transfer_offer(offer["id"], make_driver_headers(da["id"])))
    assert off["status"] == "WITHDRAWN"
    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(da["id"])))
    assert b["occupancy_status"] == "CANCELLED"


def test_no_show_booking_rejects_checkin(api):
    """PRD §3.4: "Marking a no-show advances `occupancy_status` from `RESERVED` to
    `NO_SHOW`".
    PRD §3.4: "Check-in is permitted only when ... the booking is currently `RESERVED` ... a
    check-in on a booking not in the `RESERVED` state is rejected with `ERR_INVALID_STATE`."

    A NO_SHOW (terminal) booking rejects a check-in with ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_no_show_rejects_checkin
    """
    host, driver, spot = setup_host_driver_spot(spot_overrides={"overstay_grace_minutes": 15,
                                                                "zone_code": "ZSM9"})
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    set_clock("2026-04-08T11:20:00Z")
    mark_no_show(booking["id"])
    res = api.check_in_booking(booking["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_pricing_event_cancel_does_not_requote_booking(api):
    """PRD §3.3: "Cancellation is forward-looking only: it does not re-quote any existing
    booking, because a booking's quote is frozen at creation. Only future quotes stop seeing
    the cancelled surge."

    A booking quoted 3000 under an ACTIVE 25000 bps surge keeps quoted_amount_cents at 3000
    after the event is cancelled; the event status becomes CANCELLED.

    Design: Corner/state_machines/pricing_event_cancel_does_not_requote_existing_booking
    """
    from test_helpers import create_pricing_event
    host, driver, spot = setup_host_driver_spot(
        spot_overrides={"base_hourly_cents": 400, "zone_code": "DT-SM10"}, wallet_cents=5000)
    pe = create_pricing_event("DT-SM10", "2026-04-08T00:00:00Z", "2026-04-09T00:00:00Z", 25000)
    set_clock("2026-04-08T07:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T13:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 3000
    cancelled = get_success_data(api.cancel_pricing_event(pe["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"
    b = get_success_data(api.get_booking(booking["id"], make_driver_headers(driver["id"])))
    assert b["quoted_amount_cents"] == 3000, b["quoted_amount_cents"]
