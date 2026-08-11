"""Sibling discounts, rounding policy and what the family finally owes."""

from test_helpers import (
    book_position,
    charge_for,
    confirm_enrollment,
    create_active_participant,
    create_confirmed_enrollment,
    create_fee_band,
    create_open_session,
    create_program,
    create_session,
    create_transport_run,
    open_session,
    record_payment,
    request_enrollment,
    withdraw_enrollment,
)

SIBLING_HOUSEHOLD = "HH-SIB"


def _two_siblings():
    """Two active participants sharing one household id."""
    elder = create_active_participant(
        legal_name="Ada Rivera", household_id=SIBLING_HOUSEHOLD, household_size=4,
        weight_kg=40, mobility_profile="WHEELCHAIR",
    )
    younger = create_active_participant(
        legal_name="Nia Rivera", date_of_birth="2012-01-20",
        household_id=SIBLING_HOUSEHOLD, household_size=4, weight_kg=32,
        mobility_profile="AMBULATORY",
    )
    return elder["participant"], younger["participant"]


def _priced_session_with_two_confirmed_siblings(rounding_policy, name, start_at, end_at):
    program = create_program(
        name=name, activity_type="ARTS", pricing_mode="PER_SESSION",
        rounding_policy=rounding_policy,
    )
    session = create_session(
        program["id"], start_at=start_at, end_at=end_at, slot_capacity=4
    )
    open_session(session["id"])
    elder, younger = _two_siblings()
    elder_enrollment = create_confirmed_enrollment(elder["id"], session["id"])
    create_confirmed_enrollment(younger["id"], session["id"])
    return session, elder_enrollment


def test_round_per_line_lands_one_cent_above_round_on_total():
    """PRD §3.8: "Under `ROUND_PER_LINE`, discount each line separately and round
    each separately: take `copay_cents` multiplied by 10000 minus the discount
    basis points, divided by 10000, rounded half up; take `transport_fee_cents`
    through the identical treatment; and add the two rounded results. Two
    half-cent fragments can therefore both round up."
    PRD §3.8: "Under `ROUND_ON_TOTAL`, add `copay_cents` and
    `transport_fee_cents` first, then discount and round the single sum: the
    total multiplied by 10000 minus the discount basis points, divided by 10000,
    rounded half up."
    PRD §3.7: "Under the `FLAT` variant the fare is the run's `flat_fare_cents`
    plus that surcharge, and no rounding occurs at all because both terms are
    already whole cents; `route_miles_x10` plays no part."

    Design: Difficulty/combinatorial_formula/family_responsibility_round_per_line_is_one_cent_above_round_on_total
    """
    create_fee_band(per_session_cents=5010, series_cents=30060)
    per_line_session, per_line_enrollment = _priced_session_with_two_confirmed_siblings(
        "ROUND_PER_LINE", "Inclusive Arts PL", "2026-06-10T14:00:00Z", "2026-06-10T16:00:00Z"
    )
    run = create_transport_run(
        per_line_session["id"],
        pickup_start_at="2026-06-10T13:00:00Z",
        pickup_end_at="2026-06-10T13:45:00Z",
        fare_mode="FLAT",
        flat_fare_cents=1000,
        route_miles_x10=0,
        accessible_positions=1,
        ambulatory_seats=0,
    )

    booking = book_position(run["id"], per_line_enrollment["id"], "ACCESSIBLE")
    assert booking["fare_cents"] == 1250, (
        f"1000 flat plus the 250-cent accessible surcharge; got {booking['fare_cents']}"
    )

    charge = charge_for(per_line_enrollment["id"])
    assert charge["sibling_discount_bp"] == 1500
    assert charge["copay_cents"] == 5010
    assert charge["transport_fee_cents"] == 1250
    assert charge["family_responsibility_cents"] == 5322, (
        "4258.5 rounds to 4259 and 1062.5 rounds to 1063, summing to 5322; "
        f"got {charge['family_responsibility_cents']}"
    )


def test_round_on_total_combines_the_two_fragments_inside_one_rounding_step():
    """PRD §3.8: "Under `ROUND_ON_TOTAL`, add `copay_cents` and
    `transport_fee_cents` first, then discount and round the single sum: the
    total multiplied by 10000 minus the discount basis points, divided by 10000,
    rounded half up. The two fragments now combine or cancel inside one rounding
    step."
    PRD §3.8: "On identical inputs the two policies routinely land one cent
    apart, which is why `rounding_policy` is declared per programme rather than
    assumed."

    Design: Difficulty/combinatorial_formula/family_responsibility_round_per_line_is_one_cent_above_round_on_total
    """
    create_fee_band(per_session_cents=5010, series_cents=30060)
    on_total_session, on_total_enrollment = _priced_session_with_two_confirmed_siblings(
        "ROUND_ON_TOTAL", "Inclusive Arts OT", "2026-06-17T14:00:00Z", "2026-06-17T16:00:00Z"
    )
    run = create_transport_run(
        on_total_session["id"],
        pickup_start_at="2026-06-17T13:00:00Z",
        pickup_end_at="2026-06-17T13:45:00Z",
        fare_mode="FLAT",
        flat_fare_cents=1000,
        route_miles_x10=0,
        accessible_positions=1,
        ambulatory_seats=0,
    )

    booking = book_position(run["id"], on_total_enrollment["id"], "ACCESSIBLE")
    assert booking["fare_cents"] == 1250

    charge = charge_for(on_total_enrollment["id"])
    assert charge["sibling_discount_bp"] == 1500
    assert charge["copay_cents"] == 5010
    assert charge["family_responsibility_cents"] == 5321, (
        "6260 discounted by 1500 basis points is exactly 5321; "
        f"got {charge['family_responsibility_cents']}"
    )


def _one_session_two_sibling_requests():
    create_fee_band(per_session_cents=5010, series_cents=30060)
    _program, session = create_open_session(
        program_overrides={
            "name": "Inclusive Music", "activity_type": "ARTS",
            "rounding_policy": "ROUND_ON_TOTAL",
        },
        slot_capacity=4,
    )
    elder, younger = _two_siblings()
    elder_enrollment = request_enrollment(elder["id"], session["id"])
    younger_enrollment = request_enrollment(younger["id"], session["id"])
    return session, elder_enrollment, younger_enrollment


def test_confirming_the_second_sibling_reprices_the_first_siblings_charge():
    """PRD §3.8: "Count the distinct participants who hold a `CONFIRMED`
    enrolment on this same session and whose `household_id` equals this
    participant's `household_id` — counting this participant among them. When
    that count is 2 or more, `sibling_discount_bp` is 1500; otherwise it is 0."
    PRD §3.8: "first set the enrolment's `enrollment_status` to `CONFIRMED` and
    update the session counters, then recompute this enrolment's charge so it
    counts itself, then recompute every other charge whose enrolment is
    `CONFIRMED` on the same session and whose participant shares the
    `household_id`, in `created_at` ascending order, and then stop — exactly one
    sweep, no further passes."

    Design: Difficulty/combinatorial_formula/sibling_discount_fixpoint_recomputes_the_earlier_charge
    """
    _session, elder_enrollment, younger_enrollment = _one_session_two_sibling_requests()

    confirm_enrollment(elder_enrollment["id"])
    alone = charge_for(elder_enrollment["id"])
    assert alone["family_responsibility_cents"] == 5010
    assert alone["sibling_discount_bp"] == 0

    confirm_enrollment(younger_enrollment["id"])

    elder_charge = charge_for(elder_enrollment["id"])
    assert elder_charge["sibling_discount_bp"] == 1500
    assert elder_charge["family_responsibility_cents"] == 4259, (
        "5010 discounted by 1500 basis points is 4258.5, which rounds half up to 4259; "
        f"got {elder_charge['family_responsibility_cents']}"
    )
    younger_charge = charge_for(younger_enrollment["id"])
    assert younger_charge["family_responsibility_cents"] == 4259


def test_withdrawing_the_second_sibling_restores_the_first_siblings_charge():
    """PRD §3.8: "Withdrawal is the mirror image: set the enrolment `WITHDRAWN`,
    void this charge, then re-run that same household sweep in `created_at`
    ascending order."
    PRD §3.8: "When that count is 2 or more, `sibling_discount_bp` is 1500;
    otherwise it is 0."
    PRD §3.3: "The charge is `VOIDED` when its enrolment's `enrollment_status` is
    `WITHDRAWN` or `DENIED`."

    Design: Difficulty/combinatorial_formula/sibling_discount_fixpoint_recomputes_the_earlier_charge
    """
    _session, elder_enrollment, younger_enrollment = _one_session_two_sibling_requests()
    confirm_enrollment(elder_enrollment["id"])
    confirm_enrollment(younger_enrollment["id"])
    assert charge_for(elder_enrollment["id"])["family_responsibility_cents"] == 4259

    withdraw_enrollment(younger_enrollment["id"])

    elder_charge = charge_for(elder_enrollment["id"])
    assert elder_charge["sibling_discount_bp"] == 0
    assert elder_charge["family_responsibility_cents"] == 5010
    assert charge_for(younger_enrollment["id"])["status"] == "VOIDED"


def test_charge_settles_to_zero_balance_after_the_family_payment():
    """PRD §3.8: "A `FundingOfficer` records a payment of `amount_cents` against a
    charge. The paid amount is added to `amount_paid_cents`, then `balance_cents`
    and the settlement `status` are re-derived."
    PRD §3.3: "Otherwise it is `SETTLED` when `balance_cents` is 0. Otherwise it
    is `OUTSTANDING`."

    Design: Corner/calculations/charge_settles_to_zero_balance_after_the_family_payment
    """
    create_fee_band(per_session_cents=4000)
    _program, session = create_open_session()
    who = create_active_participant()
    enrollment = create_confirmed_enrollment(who["participant"]["id"], session["id"])

    before = charge_for(enrollment["id"])
    assert before["status"] == "OUTSTANDING"
    assert before["balance_cents"] == 4000

    after = record_payment(before["id"], 4000)
    assert after["amount_paid_cents"] == 4000
    assert after["balance_cents"] == 0
    assert after["status"] == "SETTLED"
