"""State-machine corners: invalid transitions, precondition violations, initial
states, branch side-effects, and clock-driven auto-transitions."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_studio,
    set_clock,
    create_location,
    create_member,
    create_product,
    create_membership,
    create_and_activate_membership,
    create_frozen_membership,
    book_reservation,
    attach_retail_sale,
    get_member,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
)

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_cancel_membership_twice_invalid_state(api):
    """PRD 3.3: "Cancellation moves a membership from any of `PENDING`, `ACTIVE`,
    `FROZEN`, or `PAST_DUE` to `CANCELLED` and is permitted whenever the
    membership is not already `CANCELLED`".

    Cancelling an already-CANCELLED membership is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_membership_twice_invalid_state
    """
    loc = create_location(name="SMc")
    member = create_member(loc["id"])
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=4, monthly_fee_cents=6000)
    validate_success(api.cancel_membership(mbr["id"], FRONT), 200)
    resp = api.cancel_membership(mbr["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_already_active_membership_invalid_state(api):
    """PRD 3.3: "Activation moves a membership from `PENDING` to `ACTIVE` and is
    performed by a `FrontDesk` operator or `StudioAdmin`; it is permitted only
    while the membership is `PENDING`."

    Activating a membership that is already ACTIVE is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/activate_already_active_membership_invalid_state
    """
    loc = create_location(name="SMa")
    member = create_member(loc["id"])
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=4, monthly_fee_cents=6000)
    resp = api.activate_membership(mbr["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_without_checkin_invalid_state(api):
    """PRD 3.6: "Completion is performed by a `FrontDesk` operator or by the
    assigned technician, and moves a `CHECKED_IN` reservation to `COMPLETED`".

    Completing a reservation that is still BOOKED (never checked in) is rejected
    ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_without_checkin_invalid_state
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "SMcomp"},
                          service_overrides={"name": "Q", "duration_minutes": 30,
                                             "list_price_cents": 2000})
    res = book_reservation(member=studio["member"], location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="WALK_IN", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    resp = api.complete_reservation(res["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_checkin_too_early_rejected(api):
    """PRD 3.6: "Check-in ... is permitted only while the reservation is
    `BOOKED`, and only once the clock has reached at least 30 minutes before
    `start_utc`; an attempt earlier than that window is rejected with
    `ERR_CHECKIN_TOO_EARLY`."

    A check-in 60 minutes before start_utc (earlier than the 30-minute window) is
    rejected ERR_CHECKIN_TOO_EARLY.

    Design: Corner/state_machines/checkin_too_early_rejected
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Early"},
                          service_overrides={"name": "QE", "duration_minutes": 30,
                                             "list_price_cents": 2000})
    res = book_reservation(member=studio["member"], location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="WALK_IN", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    set_clock("2026-06-16T09:00:00Z")  # 60m before start
    resp = api.check_in_reservation(res["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_TOO_EARLY.value)


def test_completed_reservation_cannot_be_cancelled(api):
    """PRD 3.6: "The `booking_status` axis tracks the visit through `BOOKED`,
    `CHECKED_IN`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, with the last three
    terminal."
    PRD 3.6: "Cancellation may be requested by the owning member or a `FrontDesk`
    operator on a reservation that is `BOOKED` or `CHECKED_IN`".

    A COMPLETED reservation is terminal on the booking axis; cancelling it is
    rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/completed_reservation_is_terminal_cancel_locked
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Term"},
                          service_overrides={"name": "QT", "duration_minutes": 30,
                                             "list_price_cents": 2000})
    res = book_reservation(member=studio["member"], location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="WALK_IN", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    set_clock("2026-06-16T09:45:00Z")
    api.check_in_reservation(res["id"], FRONT)
    api.complete_reservation(res["id"], FRONT)
    resp = api.cancel_reservation(res["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_credit_reservation_initial_states(api):
    """PRD 3.4: "A new reservation begins with `booking_status` `BOOKED` and a
    `settlement_status` that depends on how it will be paid."
    PRD 3.4: "On a `CREDIT` booking the settlement axis moves from `UNSETTLED` to
    `CREDIT_HELD`: the system writes a `DEBIT` ledger entry ... sets the
    reservation's `credits_held` to that `credit_cost`".

    A new CREDIT reservation starts booking_status==BOOKED and
    settlement_status==CREDIT_HELD with credits_held==1.

    Design: Corner/state_machines/reservation_initial_states_on_create
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Init"},
                          service_overrides={"name": "QI", "duration_minutes": 30,
                                             "list_price_cents": 3000, "credit_cost": 1})
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="CREDIT", expected_room_version=studio["room"]["version"],
                           membership_id=mbr["id"], expected_membership_version=mbr["version"],
                           booked_by="frontdesk")
    assert res["booking_status"] == "BOOKED"
    assert res["settlement_status"] == "CREDIT_HELD"
    assert res["credits_held"] == 1


def test_late_cancel_mints_strike_and_forfeits(api):
    """PRD 3.6: "A late cancellation — one made less than 24 hours before
    `start_utc` — instead mints a `NoShowStrike` of kind `LATE_CANCEL`, moves the
    settlement axis to `FORFEITED`, and forfeits the money: a deposit booking's
    `deposit_held_cents` is forfeited rather than refunded ... That new strike
    raises the member's `no_show_strike_count`".

    Cancelling a DEPOSIT reservation 10 hours before start (< 24h, late) forfeits
    the deposit, moves settlement to FORFEITED, and raises no_show_strike_count
    to 1 — the branch divergent from a timely cancel (wallet stays 0).

    Design: Corner/state_machines/late_cancel_mints_strike_branch
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z",
                          location_overrides={"name": "Late", "deposit_required_cents": 1000},
                          service_overrides={"name": "QL", "duration_minutes": 30,
                                             "list_price_cents": 2000})
    member = studio["member"]
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="DEPOSIT", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    set_clock("2026-06-16T00:00:00Z")  # 10h before start -> late
    cancelled = validate_success(
        api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "FORFEITED"
    member_after = get_member(member["id"])
    assert member_after["no_show_strike_count"] == 1
    assert member_after["wallet_credit_cents"] == 0


def test_freeze_auto_expires_on_clock_advance(api):
    """PRD 3.3: "Unfreezing returns a `FROZEN` membership to `ACTIVE` — driven
    either by the member ... or automatically by the server when the clock
    reaches `freeze_until_utc` — clearing `freeze_until_utc`, writing an
    `UNFREEZE_RESTORE` ledger entry whose `delta_credits` is the positive
    `frozen_cycle_credits`".

    A PLUS membership frozen for 5 days auto-thaws to ACTIVE when the clock
    advances past freeze_until_utc, restoring the parked 4 credits.

    Design: Corner/state_machines/freeze_auto_expires_on_clock_advance
    """
    loc = create_location(name="Fz")
    member = create_member(loc["id"])
    set_clock("2026-06-15T12:00:00Z")
    mbr = create_frozen_membership(member["id"], freeze_days=5, tier="PLUS",
                                   monthly_credit_grant=4, monthly_fee_cents=6000)
    assert mbr["status"] == "FROZEN"
    set_clock("2026-06-21T00:00:00Z")  # past freeze_until 2026-06-20T12:00:00Z
    after = validate_success(api.get_membership(mbr["id"], make_member_headers(member["id"])), 200)
    assert after["status"] == "ACTIVE"
    assert after["credit_balance"] == 4
    assert after["frozen_cycle_credits"] == 0


def test_strike_waive_refunds_and_recomputes_count(api):
    """PRD 3.6: "A `StudioAdmin` may waive an `ACTIVE` strike; waiving refunds the
    strike's `fee_charged_cents` to the member's `wallet_credit_cents`, moves the
    strike to `WAIVED`, and recomputes the member's `no_show_strike_count`".

    Waiving the lone ACTIVE strike (a NO_SHOW that forfeited a 1000 deposit)
    moves it to WAIVED, refunds 1000 to the wallet, and recomputes
    no_show_strike_count to 0.

    Design: Corner/state_machines/strike_waive_recomputes_count
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z",
                          location_overrides={"name": "Wv", "deposit_required_cents": 1000},
                          service_overrides={"name": "QW", "duration_minutes": 15,
                                             "list_price_cents": 1200})
    member = studio["member"]
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="DEPOSIT", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    set_clock("2026-06-16T10:20:00Z")
    api.mark_no_show_reservation(res["id"], FRONT)
    strikes, _ = validate_paginated(
        api.list_no_show_strikes(FRONT, params={"member_id": member["id"]}))
    strike_id = strikes[0]["id"]
    waived = validate_success(api.waive_no_show_strike(strike_id, ADMIN), 200)
    assert waived["status"] == "WAIVED"
    member_after = get_member(member["id"])
    assert member_after["no_show_strike_count"] == 0
    assert member_after["wallet_credit_cents"] == 1000


def test_void_pending_retail_sale_no_stock_change(api):
    """PRD 3.7: "A `FrontDesk` operator may instead void a `PENDING` sale, moving
    it to `VOIDED` with no stock change (stock was never decremented while
    `PENDING`)".

    Voiding a PENDING retail sale moves it to VOIDED and leaves the product's
    stock_qty unchanged at 100.

    Design: Corner/state_machines/void_pending_retail_sale
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Vd"},
                          service_overrides={"name": "QV", "duration_minutes": 30,
                                             "list_price_cents": 2000})
    member = studio["member"]
    product = create_product(name="Oil", unit_price_cents=999, stock_qty=100)
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="WALK_IN", expected_room_version=studio["room"]["version"],
                           booked_by="frontdesk")
    sale = attach_retail_sale(member, res["id"], product["id"], quantity=2)
    voided = validate_success(api.void_retail_sale(sale["id"], FRONT), 200)
    assert voided["status"] == "VOIDED"
    prod_after = validate_success(api.get_product(product["id"], ADMIN), 200)
    assert prod_after["stock_qty"] == 100


def test_renew_failed_payment_moves_to_past_due(api):
    """PRD 3.3: "When a renewal on an `ACTIVE` membership reports a
    `payment_outcome` of `FAILED`, the membership branches to `PAST_DUE`: no
    `GRANT` is written, the `credit_balance` is left unchanged, and only the
    `version` advances."

    Renewing an ACTIVE PLUS membership (4 credits) with payment_outcome=FAILED
    moves it to PAST_DUE, leaves credit_balance at 4, and does not advance
    cycle_index.

    Design: Corner/state_machines/renew_failed_payment_moves_past_due
    """
    loc = create_location(name="Pd")
    member = create_member(loc["id"])
    set_clock("2026-06-15T12:00:00Z")
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=4, monthly_fee_cents=6000,
                                         max_rollover_credits=4)
    data = validate_success(api.renew_membership(mbr["id"], {"payment_outcome": "FAILED"}, FRONT), 200)
    assert data["status"] == "PAST_DUE"
    assert data["credit_balance"] == 4
    assert data["cycle_index"] == 0
