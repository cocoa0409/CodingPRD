"""Confirm, voluntary cancellation settlement tiers, and payment conservation."""
from test_helpers import (
    ApiErrorId,
    assert_payment_conservation,
    cancel_booking,
    confirm_booking,
    create_aircraft,
    create_booking,
    create_flight,
    create_pilot,
    get_booking,
    get_flight,
    list_credits_for_booking,
    mint_credit_via_ops_cancellation,
    passenger_entry,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import create_season

AGENT = TEST_USERS["booking_agent_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_confirm_wrong_amount_payment_mismatch(api):
    """PRD §3.5: "Confirming collects the card: `card_amount_cents` must
    equal `quoted_total_cents` minus `credits_applied_cents` to the cent,
    otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402) — and the expiry check
    runs first, so an expired hold surfaces as `ERR_BOOKING_HOLD_EXPIRED`
    even when the amount is also wrong."
    PRD §3.5: "A successful confirm moves HELD → CONFIRMED, records
    `card_amount_cents` into `paid_cents`, and clears `expires_at` to null."

    Design: Corner/validations/confirm_wrong_amount_payment_mismatch
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])

    # One cent short of the 25000 balance due.
    resp = api.confirm_booking(booking["id"], {"card_amount_cents": 24999}, AGENT)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    confirmed = confirm_booking(booking["id"], 25000)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["paid_cents"] == 25000
    assert confirmed["expires_at"] is None, "confirm clears the hold expiry"


def test_confirm_or_apply_credit_after_hold_expiry(api):
    """PRD §3.5: "While HELD, two desk operations are available, and both
    require the hold to be live — at or past `expires_at` either is rejected
    with `ERR_BOOKING_HOLD_EXPIRED`."
    PRD §2.8: "Expiry checks fire at the boundary itself — a hold or credit
    whose `expires_at` is at or before the current instant is expired —
    while a scheduled departure must be strictly in the future."

    Design: Corner/validations/confirm_or_apply_credit_after_hold_expiry
    """
    env, _f2, _b0, credit = mint_credit_via_ops_cancellation()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])

    # Created at 00:00 with the default 30-minute hold; 00:31 is past expiry.
    set_clock("2026-08-03T00:31:00Z")
    resp = api.confirm_booking(booking["id"], {"card_amount_cents": 25000}, AGENT)
    validate_error(resp, ApiErrorId.ERR_BOOKING_HOLD_EXPIRED)

    resp = api.apply_credit(booking["id"], {"credit_id": credit["id"]}, AGENT)
    validate_error(resp, ApiErrorId.ERR_BOOKING_HOLD_EXPIRED)

    # The expiry sweep has not run, so the booking itself is still HELD.
    assert get_booking(booking["id"])["status"] == "HELD"


def _setup_three_flights_three_bookings(api):
    """Three flights on three aircraft with three pilots, all departing
    2026-08-05T14:00:00Z; one CONFIRMED 25000-cent booking per flight."""
    env = setup_ops_env()
    a2 = create_aircraft(tail_number="N2")
    a3 = create_aircraft(tail_number="N3")
    p2 = create_pilot(display_name="Pat Two", certificate_no="C2")
    p3 = create_pilot(display_name="Pat Three", certificate_no="C3")
    combos = [
        (env["aircraft"], env["pilot"]),
        (a2, p2),
        (a3, p3),
    ]
    bookings = []
    for aircraft, pilot in combos:
        flight = create_flight(env, "2026-08-05T14:00:00Z",
                               aircraft=aircraft, pilot=pilot)
        booking = create_booking(flight["id"], [passenger_entry("PX", 100)])
        confirm_booking(booking["id"], 25000)
        bookings.append(booking)
    return env, bookings


def test_cancel_refund_tier_boundaries(api):
    """PRD §3.8: "At twenty-four hours or more, the full `paid_cents` refunds
    to card and `retained_fee_cents` stays 0. Between two hours and
    twenty-four hours, the retained fee is ten percent of `paid_cents`
    rounded half-up, and the remainder refunds. Inside two hours there is no
    card refund: a credit leg of seventy-five percent of `paid_cents`,
    rounded half-up, is minted as a new `RebookingCredit`, and the fee keeps
    the remainder."

    Design: Corner/calculations/cancel_refund_tier_boundaries
    """
    env, (b1, b2, b3) = _setup_three_flights_three_bookings(api)

    # Exactly 1440 minutes before departure: full-refund tier (>= boundary).
    set_clock("2026-08-04T14:00:00Z")
    r1 = cancel_booking(b1["id"])
    assert (r1["refunded_card_cents"], r1["retained_fee_cents"],
            r1["credited_cents"]) == (25000, 0, 0)

    # Exactly 120 minutes before: partial tier, fee == 10% rounded half-up.
    set_clock("2026-08-05T12:00:00Z")
    r2 = cancel_booking(b2["id"])
    assert (r2["refunded_card_cents"], r2["retained_fee_cents"],
            r2["credited_cents"]) == (22500, 2500, 0)

    # 119 minutes before: credit-only tier, credit == 75% rounded half-up.
    set_clock("2026-08-05T12:01:00Z")
    r3 = cancel_booking(b3["id"])
    assert (r3["refunded_card_cents"], r3["retained_fee_cents"],
            r3["credited_cents"]) == (0, 6250, 18750)

    # A RebookingCredit is minted only in the credit-only tier.
    credits3 = list_credits_for_booking(b3["id"])
    assert len(credits3) == 1 and credits3[0]["amount_cents"] == 18750
    assert list_credits_for_booking(b1["id"]) == []
    assert list_credits_for_booking(b2["id"]) == []

    for rb in (r1, r2, r3):
        assert_payment_conservation(rb)


def _setup_mid_window_cancel(api):
    """CONFIRMED booking paid 30000 (25000 * 1.20 PEAK season) on a flight
    departing Tuesday 2026-08-18T11:00:00Z; clock 2026-08-17T12:00:00Z, i.e.
    1380 minutes before departure (mid tier)."""
    env = setup_ops_env(clock="2026-08-17T12:00:00Z")
    create_season(label="PEAK", start_date="2026-06-01", end_date="2026-09-01",
                  multiplier_bps=12000)
    flight = create_flight(env, "2026-08-18T11:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 100)])
    assert booking["quoted_total_cents"] == 30000
    confirm_booking(booking["id"], 30000)
    return env, flight, booking


def test_mid_window_cancel_splits_payment_into_refund_and_fee(api):
    """PRD §3.8: "Between two hours and twenty-four hours, the retained fee
    is ten percent of `paid_cents` rounded half-up, and the remainder
    refunds."
    PRD §3.8: "In every tier `refunded_card_cents` grows by the refunded leg,
    and the fiscal invariant holds to the cent: `paid_cents` always equals
    `refunded_card_cents` plus `credited_cents` plus `retained_fee_cents`."

    Design: Difficulty/compensating_invariant/payment_conservation_across_mid_window_cancel
    """
    env, flight, booking = _setup_mid_window_cancel(api)
    cancelled = cancel_booking(booking["id"])
    # 1380 minutes out is inside [120, 1440): fee == round_half_up(30000 *
    # 0.10) == 3000, remainder refunds.
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refunded_card_cents"] == 27000
    assert cancelled["retained_fee_cents"] == 3000
    assert cancelled["credited_cents"] == 0


def test_payment_buckets_conserve_paid_cents(api):
    """PRD §3.8: "In every tier `refunded_card_cents` grows by the refunded
    leg, and the fiscal invariant holds to the cent: `paid_cents` always
    equals `refunded_card_cents` plus `credited_cents` plus
    `retained_fee_cents`."
    PRD §3.8: "Inside two hours there is no card refund: a credit leg of
    seventy-five percent of `paid_cents`, rounded half-up, is minted as a new
    `RebookingCredit`, and the fee keeps the remainder."

    Design: Difficulty/compensating_invariant/payment_conservation_across_mid_window_cancel
    """
    env, flight, booking = _setup_mid_window_cancel(api)
    cancelled = cancel_booking(booking["id"])
    assert cancelled["paid_cents"] == 30000
    assert_payment_conservation(cancelled)
    # The mid tier mints no credit; cents are conserved to the cent.
    assert list_credits_for_booking(booking["id"]) == []


def test_mutation_result_visible_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.8: "At twenty-four hours or more, the full `paid_cents` refunds to
    card and `retained_fee_cents` stays 0."

    Design: Corner/consistency_model/mutation_result_visible_in_same_response
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-05T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])
    confirm_booking(booking["id"], 25000)

    # The CANCEL response itself carries the new status and full settlement
    # (clock 08-03, departure 08-05 14:00 -> well over 24 hours -> full tier).
    cancelled = cancel_booking(booking["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refunded_card_cents"] == 25000
    assert cancelled["retained_fee_cents"] == 0
    assert cancelled["credited_cents"] == 0

    # The seat release is visible without any reconciliation lag.
    assert get_flight(flight["id"])["seats_booked"] == 0


def test_confirm_on_expired_booking_reports_state_not_payment(api):
    """PRD §2.9: "Every endpoint evaluates its guards in a fixed global
    order, and a failure at an earlier rung masks every later one."
    PRD §2.9: "6. **State** — the target resource is in a state that permits
    the requested transition; terminal states reject every transition.
    Failure: `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.9: "11. **Business fiscal rules** — exact payment amounts and
    credit redeemability."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_payment_mismatch
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-05T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])
    # HELD -> EXPIRED via the ops-cancellation cascade.
    validate_success(
        api.flight_event(
            flight["id"], {"event_type": "CANCEL_OPS", "reason": "manual"}, DISP
        )
    )
    assert get_booking(booking["id"])["status"] == "EXPIRED"

    # The amount is also wrong (1 cent), but the state rung fires first.
    resp = api.confirm_booking(booking["id"], {"card_amount_cents": 1}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_failed_confirm_leaves_expired_booking_unchanged(api):
    """PRD §2.9: "Every endpoint evaluates its guards in a fixed global
    order, and a failure at an earlier rung masks every later one."
    PRD §3.8: "the bookings move the same way: HELD bookings become EXPIRED
    with no refund; CONFIRMED and CHECKED_IN bookings become CREDITED, their
    `credited_cents` set to `paid_cents`, and a `RebookingCredit` is minted
    for `paid_cents` plus `credits_applied_cents`"

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_payment_mismatch
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-05T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])
    validate_success(
        api.flight_event(
            flight["id"], {"event_type": "CANCEL_OPS", "reason": "manual"}, DISP
        )
    )

    resp = api.confirm_booking(booking["id"], {"card_amount_cents": 1}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_booking(booking["id"])
    assert after["status"] == "EXPIRED", "cascade result unchanged"
    assert after["paid_cents"] == 0
    assert after["refunded_card_cents"] == 0
