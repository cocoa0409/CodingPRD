"""Booking workflow: BOOKED branching to COMPLETED / NO_SHOW / CANCELLED, the credit
waterfall cascade, and conservation invariants on credit_balance and open_booking_count.
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_technician_headers,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]

COMPRESSION = {"code": "COMPRESSION", "name": "Compression",
               "duration_minutes": 30, "buffer_minutes": 0, "credit_cost": 1,
               "requires_medical_clearance": False}
BASE_PLAN = {"tier": "BASE", "monthly_fee_cents": 9900,
             "monthly_credit_grant": 4, "rollover_cap": 0}


# ─── Queue A: non_linear_state_machine (booking branching) ───────────────────
def test_no_show_branch_forfeits_credits_and_charges_fee(api):
    """PRD §3.5: "it moves the booking from BOOKED to NO_SHOW, assesses the fee in no-show
    mode (see Section 3.7), forfeits the consumed credits (a no-show does not refund the
    session credits), and decrements the location's open_booking_count."

    Design: Difficulty/non_linear_state_machine/booking_branching_to_completed_no_show_cancelled
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    fx.set_clock("2026-06-15T10:05:00Z")

    result = validate_success(
        api.no_show_booking(booking["id"], make_technician_headers(s.technician["id"])), 200)
    assert result["status"] == "NO_SHOW"
    assert result["fee_charged_cents"] == 5000, result
    member = fx.get_member(s.member["id"])
    assert member["credit_balance"] == 3, member  # credit forfeited, not refunded


def test_completed_branch_keeps_credits_no_fee(api):
    """PRD §3.5: "it moves the booking from BOOKED to COMPLETED and decrements the
    location's open_booking_count."
    PRD §3.5: "Completing a session is permitted only while the booking is BOOKED, only
    when the acting technician has a SCHEDULED shift at the booking's location covering the
    booking's starts_at, and only once the clock has reached or passed the booking's
    starts_at".

    Design: Difficulty/non_linear_state_machine/booking_branching_to_completed_no_show_cancelled
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    fx.set_clock("2026-06-15T10:05:00Z")

    result = validate_success(
        api.complete_booking(booking["id"], make_technician_headers(s.technician["id"])), 200)
    assert result["status"] == "COMPLETED"
    assert result["fee_charged_cents"] == 0, result
    member = fx.get_member(s.member["id"])
    assert member["credit_balance"] == 3, member  # credit kept (consumed by completed session)


# ─── Queue A: transitive_cascade (booking depletes pack depth-3) ─────────────
def test_booking_depletes_only_pack_cascade(api):
    """PRD §3.5: "The booking records the source it drew from in credit_source: SUBSCRIPTION
    when the entire cost came from the subscription, PACK when none came from the
    subscription, and SPLIT when it drew partly from each. Whenever a pack's last remaining
    credit is consumed, that pack transitions from ACTIVE to DEPLETED."
    PRD §3.6: "plus the sum of remaining_credits across all of the member's credit packs
    whose status is ACTIVE."

    Design: Difficulty/transitive_cascade/booking_create_depletes_pack_cascade_depth3
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   with_subscription=False)
    pack = fx.buy_pack(s.member["id"], 1, is_intro=False)

    booking = validate_success(api.create_booking({
        "member_id": s.member["id"], "location_id": s.location["id"],
        "room_id": s.room["id"], "starts_at": "2026-06-15T10:00:00Z",
        "expected_room_version": s.room_version,
    }, make_member_headers(s.member["id"])), 201)
    assert booking["credit_source"] == "PACK", booking

    after_pack = fx.get_credit_pack(pack["id"])
    assert after_pack["remaining_credits"] == 0
    assert after_pack["status"] == "DEPLETED"
    member = fx.get_member(s.member["id"])
    assert member["credit_balance"] == 0, member


def test_booking_from_subscription_source(api):
    """PRD §3.5: "The system first takes from the subscription's granted credits: the amount
    taken from the subscription is the smaller of the cost and the subscription's
    granted_credits_remaining when the subscription is ACTIVE".
    PRD §3.5: "SUBSCRIPTION when the entire cost came from the subscription".

    Design: Difficulty/transitive_cascade/booking_create_depletes_pack_cascade_depth3
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    booking = validate_success(api.create_booking({
        "member_id": s.member["id"], "location_id": s.location["id"],
        "room_id": s.room["id"], "starts_at": "2026-06-15T10:00:00Z",
        "expected_room_version": s.room_version,
    }, make_member_headers(s.member["id"])), 201)
    assert booking["credit_source"] == "SUBSCRIPTION", booking
    assert booking["credits_charged"] == 1
    after = fx.get_subscription(s.subscription["id"])
    assert after["granted_credits_remaining"] == 3, after


# ─── Queue A: compensating_invariant ────────────────────────────────────────
def test_free_cancel_conserves_member_credits(api):
    """PRD §3.5: "It moves the booking from BOOKED to CANCELLED, assesses the late-cancel
    fee in cancel mode (see Section 3.7), refunds the charged credits to their original
    source, recomputes the member's credit_balance, and decrements the location's
    open_booking_count."
    PRD §3.7: "in cancel mode only, if the notice is at least the free-cancellation window
    of 240 minutes, the fee is 0."

    Design: Difficulty/compensating_invariant/book_then_free_cancel_conserves_member_credits
    """
    s = fx.setup_bookable_scenario(
        service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
        clock="2026-06-15T00:00:00Z",
        shift_starts_at="2026-06-16T08:00:00Z", shift_ends_at="2026-06-16T18:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-16T10:00:00Z", s.room_version)

    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_member_headers(s.member["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_charged_cents"] == 0, cancelled  # notice >= 240 min
    member = fx.get_member(s.member["id"])
    assert member["credit_balance"] == 4, member  # debit of 1 fully compensated


def test_cancel_conserves_open_booking_count(api):
    """PRD §3.5: "Creating a booking increments the room's version by one, increments the
    owning location's open_booking_count, and recomputes the member's credit_balance."
    PRD §3.5: "It moves the booking from BOOKED to CANCELLED ... and decrements the
    location's open_booking_count."

    Design: Difficulty/compensating_invariant/book_then_cancel_conserves_open_booking_count
    """
    s = fx.setup_bookable_scenario(
        service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
        clock="2026-06-15T00:00:00Z",
        shift_starts_at="2026-06-16T08:00:00Z", shift_ends_at="2026-06-16T18:00:00Z")
    loc_before = fx.get_location(s.location["id"])
    assert loc_before["open_booking_count"] == 0

    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-16T10:00:00Z", s.room_version)
    loc_after_book = fx.get_location(s.location["id"])
    assert loc_after_book["open_booking_count"] == 1, loc_after_book

    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_member_headers(s.member["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    loc_after_cancel = fx.get_location(s.location["id"])
    assert loc_after_cancel["open_booking_count"] == 0, loc_after_cancel


def test_free_cancel_refund_returns_credit_to_subscription(api):
    """PRD §3.5: "The credit refund returns the charged credits to where they came from: the
    portion originally taken from the subscription is added back to the subscription's
    granted_credits_remaining first, up to what was taken from it".
    PRD §3.7: "in cancel mode only, if the notice is at least the free-cancellation window of
    240 minutes, the fee is 0."

    Design: Difficulty/compensating_invariant/book_then_free_cancel_conserves_member_credits
    """
    s = fx.setup_bookable_scenario(
        service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
        clock="2026-06-15T00:00:00Z",
        shift_starts_at="2026-06-16T08:00:00Z", shift_ends_at="2026-06-16T18:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-16T10:00:00Z", s.room_version)
    assert fx.get_subscription(s.subscription["id"])["granted_credits_remaining"] == 3

    validate_success(api.cancel_booking(booking["id"], make_member_headers(s.member["id"])), 200)
    # The 1 subscription credit drawn is returned to granted_credits_remaining.
    after = fx.get_subscription(s.subscription["id"])
    assert after["granted_credits_remaining"] == 4, after


def test_no_show_does_not_change_open_count_back(api):
    """PRD §3.5: "it moves the booking from BOOKED to NO_SHOW, assesses the fee in no-show
    mode (see Section 3.7), forfeits the consumed credits (a no-show does not refund the
    session credits), and decrements the location's open_booking_count."
    PRD §3.5: "Creating a booking increments the room's version by one, increments the owning
    location's open_booking_count".

    Design: Difficulty/compensating_invariant/book_then_cancel_conserves_open_booking_count
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    assert fx.get_location(s.location["id"])["open_booking_count"] == 1
    fx.set_clock("2026-06-15T10:05:00Z")

    validate_success(
        api.no_show_booking(booking["id"], make_technician_headers(s.technician["id"])), 200)
    # Leaving BOOKED (via NO_SHOW) decrements the count back to 0.
    assert fx.get_location(s.location["id"])["open_booking_count"] == 0


# ─── Queue B: state-machine corner instances ────────────────────────────────
def test_second_cancel_on_cancelled_booking_invalid_state(api):
    """PRD §3.5: "Cancellation is a member action (or LocationManager proxy) permitted only
    while the booking is BOOKED and only while the clock is still strictly before the
    booking's starts_at."

    Design: Corner/state_machines/cancel_already_cancelled_booking_invalid_state
    """
    s = fx.setup_bookable_scenario(
        service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
        clock="2026-06-15T00:00:00Z",
        shift_starts_at="2026-06-16T08:00:00Z", shift_ends_at="2026-06-16T18:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-16T10:00:00Z", s.room_version)
    validate_success(api.cancel_booking(booking["id"], make_member_headers(s.member["id"])), 200)

    res = api.cancel_booking(booking["id"], make_member_headers(s.member["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    member = fx.get_member(s.member["id"])
    assert member["credit_balance"] == 4, member  # no double refund


def test_complete_before_start_time_invalid_state(api):
    """PRD §3.5: "Completing a session is permitted only while the booking is BOOKED, only
    when the acting technician has a SCHEDULED shift at the booking's location covering the
    booking's starts_at, and only once the clock has reached or passed the booking's
    starts_at".

    Design: Corner/state_machines/complete_booking_before_start_time_invalid_state
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    # clock stays at 09:00 (before 10:00 start)
    res = api.complete_booking(booking["id"], make_technician_headers(s.technician["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = fx.get_booking(booking["id"])
    assert after["status"] == "BOOKED"


def test_insufficient_credits_no_wallet(api):
    """PRD §3.5: "Finally, the credit waterfall must be able to cover the service's
    credit_cost, or the request fails with ERR_INSUFFICIENT_CREDITS (HTTP 422) and no
    credits are debited."

    Design: Corner/validations/error_insufficient_credits_no_wallet
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   with_subscription=False)
    res = api.create_booking({
        "member_id": s.member["id"], "location_id": s.location["id"],
        "room_id": s.room["id"], "starts_at": "2026-06-15T10:00:00Z",
        "expected_room_version": s.room_version,
    }, make_member_headers(s.member["id"]))
    validate_error(res, "ERR_INSUFFICIENT_CREDITS")


def test_no_technician_on_duty_uncovered_slot(api):
    """PRD §3.5: "The booking's occupied interval must be fully covered by at least one
    SCHEDULED technician shift at the booking's location, or the request fails with
    ERR_NO_TECHNICIAN_ON_DUTY (HTTP 409)."

    Design: Corner/validations/error_no_technician_on_duty_uncovered_slot
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   with_shift=False)
    res = api.create_booking({
        "member_id": s.member["id"], "location_id": s.location["id"],
        "room_id": s.room["id"], "starts_at": "2026-06-15T10:00:00Z",
        "expected_room_version": s.room_version,
    }, make_member_headers(s.member["id"]))
    validate_error(res, "ERR_NO_TECHNICIAN_ON_DUTY")


def test_service_inactive_booking_blocked(api):
    """PRD §3.5: "The room's ServiceType must have active true, or the request fails with
    ERR_SERVICE_INACTIVE (HTTP 409)."

    Design: Corner/validations/error_service_inactive_booking_blocked
    """
    s = fx.setup_bookable_scenario(
        service_overrides={**COMPRESSION, "active": False},
        plan_overrides=BASE_PLAN, clock="2026-06-15T09:00:00Z")
    res = api.create_booking({
        "member_id": s.member["id"], "location_id": s.location["id"],
        "room_id": s.room["id"], "starts_at": "2026-06-15T10:00:00Z",
        "expected_room_version": s.room_version,
    }, make_member_headers(s.member["id"]))
    validate_error(res, "ERR_SERVICE_INACTIVE")
