"""Deposit ledger claims: the two-variant settlement (provisional hold at confirm,
final release+consume at post), the conservation invariant under a forward
HOLD + compensating RELEASE, insufficient-deposit rejection, and immediate
visibility of the hold.
"""
from test_helpers import (
    get_success_data, validate_error,
    DISPATCHER,
    ApiErrorId,
    setup_active_enrollment, create_aircraft, create_booking,
    setup_confirmed_booking, get_student, get_booking,
    create_draft_flight_log,
    make_instructor_headers,
    list_deposit_transactions, assert_ledger_conservation,
)


def test_provisional_hold_then_final_consume_settlement(api):
    """PRD §3.7: "The provisional variant fires when a booking is confirmed: it
    records a `HOLD` for the booking's `estimated_cost_cents`, increasing
    `deposit_held_cents` by that amount and decreasing `deposit_balance_cents` by
    the same amount."
    PRD §3.7: "The release reduces `deposit_held_cents` by the estimate, the consume
    increases `deposit_consumed_cents` by the actual charge, and
    `deposit_balance_cents` is adjusted by the estimate minus the actual..."

    Design: Difficulty/dual_variant_calc/deposit_settlement_provisional_vs_final
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000, billing_basis="HOBBS")
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    assert booking["estimated_cost_cents"] == 42000

    # Provisional variant at confirm.
    api.confirm_booking(booking["id"], DISPATCHER)
    stu = get_student(base["student"]["id"])
    assert stu["deposit_held_cents"] == 42000
    assert stu["deposit_balance_cents"] == 58000
    assert stu["deposit_consumed_cents"] == 0

    # Drive to a posted flight log: actual 35700.
    api.dispatch_booking(booking["id"], DISPATCHER)
    fl = create_draft_flight_log(
        booking["id"], base["instructor"]["id"], 100.0, 101.7, 200.0, 201.4, 1,
    )
    get_success_data(api.post_flight_log(fl["id"], make_instructor_headers(base["instructor"]["id"])))

    # Final variant at post: release 42000, consume 35700, balance += (42000-35700).
    stu = get_student(base["student"]["id"])
    assert stu["deposit_held_cents"] == 0
    assert stu["deposit_consumed_cents"] == 35700
    assert stu["deposit_balance_cents"] == 64300


def test_settlement_ledger_conservation_after_post(api):
    """PRD §2.10: "at all times after any settlement, `deposit_balance_cents` equals
    the sum of all `DEPOSIT` amounts, minus the sum of all `HOLD` amounts, plus the
    sum of all `RELEASE` amounts, minus the sum of all `CONSUME` amounts;
    `deposit_held_cents` equals the sum of all `HOLD` amounts minus the sum of all
    `RELEASE` amounts; and `deposit_consumed_cents` equals the sum of all `CONSUME`
    amounts."

    Design: Difficulty/dual_variant_calc/deposit_settlement_provisional_vs_final
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000, billing_basis="HOBBS")
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    api.confirm_booking(booking["id"], DISPATCHER)
    api.dispatch_booking(booking["id"], DISPATCHER)
    fl = create_draft_flight_log(booking["id"], base["instructor"]["id"], 100.0, 101.7, 200.0, 201.4, 1)
    get_success_data(api.post_flight_log(fl["id"], make_instructor_headers(base["instructor"]["id"])))

    stu = get_student(base["student"]["id"])
    txns = list_deposit_transactions(base["student"]["id"])
    assert_ledger_conservation(stu, txns)


def test_confirm_then_cancel_conserves_balance(api):
    """PRD §3.7: "Booking cancellation of a confirmed booking and a no-show each
    record a `RELEASE` for the booking's `estimated_cost_cents`, returning the held
    funds to the balance. All these amounts are whole cents and no rounding is
    introduced at settlement."

    Design: Difficulty/compensating_invariant/deposit_conservation_confirm_then_cancel
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    # After confirm: 42000 held, balance 58000.
    stu = get_student(ctx["student"]["id"])
    assert stu["deposit_balance_cents"] == 58000
    assert stu["deposit_held_cents"] == 42000

    api.cancel_booking(ctx["booking"]["id"], DISPATCHER)

    stu = get_student(ctx["student"]["id"])
    assert stu["deposit_balance_cents"] == 100000
    assert stu["deposit_held_cents"] == 0
    assert stu["deposit_consumed_cents"] == 0
    assert get_booking(ctx["booking"]["id"])["status"] == "CANCELLED"


def test_confirm_then_cancel_ledger_conservation(api):
    """PRD §2.10: "at all times after any settlement, `deposit_balance_cents` equals
    the sum of all `DEPOSIT` amounts, minus the sum of all `HOLD` amounts, plus the
    sum of all `RELEASE` amounts, minus the sum of all `CONSUME` amounts..."

    Design: Difficulty/compensating_invariant/deposit_conservation_confirm_then_cancel
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    api.cancel_booking(ctx["booking"]["id"], DISPATCHER)
    stu = get_student(ctx["student"]["id"])
    txns = list_deposit_transactions(ctx["student"]["id"])
    assert_ledger_conservation(stu, txns)


def test_confirm_with_balance_one_cent_short_rejected(api):
    """PRD §3.3: "Finally, the student's `deposit_balance_cents` must be at least the
    booking's `estimated_cost_cents`, or the confirm fails with
    `ERR_INSUFFICIENT_DEPOSIT` (HTTP 402)."

    Design: Corner/validations/insufficient_deposit_confirm_one_cent_short
    """
    base = setup_active_enrollment(deposit_cents=41999, min_deposit_cents=40000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    assert booking["estimated_cost_cents"] == 42000
    validate_error(api.confirm_booking(booking["id"], DISPATCHER), ApiErrorId.ERR_INSUFFICIENT_DEPOSIT.value)
    stu = get_student(base["student"]["id"])
    assert stu["deposit_held_cents"] == 0
    assert get_booking(booking["id"])["status"] == "REQUESTED"


def test_hold_is_visible_immediately_after_confirm(api):
    """PRD §3.3: "On success the booking becomes `CONFIRMED` and a provisional hold
    of `estimated_cost_cents` is placed on the deposit ledger (see §3.7)."
    PRD §2.10: "`deposit_held_cents` is the sum currently provisionally held against
    in-flight confirmed and dispatched bookings..."

    Design: Corner/consistency_model/confirm_response_reflects_hold_immediately
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    stu = get_success_data(api.get_student(ctx["student"]["id"], DISPATCHER))
    assert stu["deposit_held_cents"] == 42000
    assert stu["deposit_balance_cents"] == 58000
