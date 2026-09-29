"""Charge assembly: mixed fee variants, irregular-operations fees, tiers, refunds.

The assembly has a pinned evaluation order with exactly one rounding point, and
its identity must balance after every write, including after a refund.
"""

from test_helpers import (
    SECOND_ACCEPTANCE_AGENT_ID,
    assert_charge_identity,
    assert_flight_leg_state,
    assert_reservation_money,
    assert_reservation_state,
    assert_segment_state,
    get_success_data,
    validate_success,
)


def test_mixed_variant_subtotal_crosses_loyalty_tier_on_acceptance(
    api, workbench, two_leg_confirmed_booking
):
    """Accepting the first leg finalises one slot and leaves the second provisional,
    so the itinerary legitimately carries two variants at once.

    PRD §3.8: "A multi-leg itinerary can therefore legitimately carry one finalised
    slot and one still-provisional slot at the same moment, and the reservation's
    `subtotal_amount` is the mixed-variant sum of both."

    Design: Difficulty/dual_variant_calc/mixed_variant_subtotal_crosses_loyalty_tier_on_acceptance
    """
    state = two_leg_confirmed_booking()

    assert_segment_state(
        workbench.read_segment(state["segment1_id"]),
        status="RESERVED",
        segment_fee_amount=33180,
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )
    assert_segment_state(
        workbench.read_segment(state["segment2_id"]),
        status="RESERVED",
        segment_fee_amount=27650,
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )

    workbench.amend_animal(state["animal_id"], measured_weight_kg=27)
    accepted = validate_success(
        api.accept_segment_assignment(
            state["segment1_id"], workbench.acceptance(SECOND_ACCEPTANCE_AGENT_ID)
        )
    )
    assert_segment_state(
        accepted,
        status="ACCEPTED",
        segment_fee_amount=37560,
        fee_variant="FINAL_AT_ACCEPTANCE",
    )
    assert_segment_state(
        workbench.read_segment(state["segment2_id"]),
        status="RESERVED",
        segment_fee_amount=27650,
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )


def test_mixed_variant_acceptance_lifts_the_booking_into_the_mid_loyalty_tier(
    api, workbench, two_leg_confirmed_booking
):
    """The mixed-variant sum lands just above the mid threshold, and the discount
    lands exactly on a half minor unit, which rounds away from zero.

    PRD §3.8: "`loyalty_tier_pct` is one tenth when `subtotal_amount` is at least
    100000 minor units, otherwise one twentieth when `subtotal_amount` is at least
    65000 minor units, otherwise zero. Tier selection reads `subtotal_amount` alone
    and never the post-refund base."

    Design: Difficulty/dual_variant_calc/mixed_variant_subtotal_crosses_loyalty_tier_on_acceptance
    """
    state = two_leg_confirmed_booking()

    before = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        before,
        subtotal_amount=60830,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        net_payable_amount=60830,
    )

    workbench.amend_animal(state["animal_id"], measured_weight_kg=27)
    workbench.accept_segment(
        state["segment1_id"], as_user_id=SECOND_ACCEPTANCE_AGENT_ID
    )

    after = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        after,
        subtotal_amount=65210,
        irops_fee_total=0,
        loyalty_tier_pct=0.05,
        loyalty_discount_amount=3261,
        refunded_amount=0,
        net_payable_amount=61949,
    )
    assert_charge_identity(after)


def test_loyalty_tier_keyed_on_subtotal_including_irops_fees(
    api, workbench, two_leg_confirmed_booking
):
    """Two care sweeps add the fees that carry the booking over the tier boundary
    the segment fees alone could not reach.

    PRD §3.8: "`subtotal_amount` is the sum of `segment_fee_amount` over **every**
    slot belonging to **every** animal record of the reservation, in **any** status —
    released and offloaded slots stay in this gross sum and are offset through
    `refunded_amount` rather than removed, which is what keeps `net_payable_amount`
    from going negative — plus the reservation's `irops_fee_total`."

    Design: Difficulty/combinatorial_formula/loyalty_tier_keyed_on_subtotal_including_irops_fees
    """
    state = two_leg_confirmed_booking()

    before = workbench.read_charge_summary(state["reservation_id"])
    assert before["subtotal_amount"] == 60830
    assert before["irops_fee_total"] == 0
    assert before["loyalty_tier_pct"] == 0
    assert before["invariant_holds"] is True

    first_sweep = workbench.sweep_irops(state["leg1_id"])
    assert first_sweep["affected_animal_count"] == 1
    assert first_sweep["total_fee_charged"] == 3500
    second_sweep = workbench.sweep_irops(state["leg1_id"])
    assert second_sweep["total_fee_charged"] == 3500

    reservation = workbench.read_reservation(state["reservation_id"])
    assert reservation["irops_fee_total"] == 7000
    assert reservation["subtotal_amount"] == 67830


def test_loyalty_tier_boundary_reached_only_through_the_care_fees(
    api, workbench, two_leg_confirmed_booking
):
    """With the care fees in the subtotal the mid rate applies, and the discount is
    the single rounding point of the assembly.

    PRD §3.8: "`loyalty_discount_amount` is `subtotal_amount` minus
    `refunded_amount`, multiplied by `loyalty_tier_pct`, rounded half up to whole
    minor units. This is the single rounding point in the whole assembly."

    Design: Difficulty/combinatorial_formula/loyalty_tier_keyed_on_subtotal_including_irops_fees
    """
    state = two_leg_confirmed_booking()
    workbench.sweep_irops(state["leg1_id"])
    workbench.sweep_irops(state["leg1_id"])

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        reservation,
        subtotal_amount=67830,
        irops_fee_total=7000,
        loyalty_tier_pct=0.05,
        loyalty_discount_amount=3392,
        refunded_amount=0,
        net_payable_amount=64438,
    )
    assert_charge_identity(reservation)
    assert_segment_state(
        workbench.read_segment(state["segment1_id"]), segment_fee_amount=33180
    )


def test_reservation_money_identity_survives_cancellation_refund(
    api, workbench, two_leg_confirmed_booking
):
    """Cancelling refunds half the gross subtotal, releases every held slot and
    leaves the money identity balanced.

    PRD §3.4: "The reservation's `refunded_amount` is incremented by half of its
    `subtotal_amount`, rounded half up. The charge assembly then re-runs, so the
    money identity still holds after the cancellation."

    Design: Difficulty/compensating_invariant/reservation_money_identity_survives_cancellation_refund
    """
    state = two_leg_confirmed_booking()
    workbench.sweep_irops(state["leg1_id"])
    workbench.sweep_irops(state["leg1_id"])

    cancelled = workbench.cancel_reservation(state["reservation_id"])
    assert_reservation_state(cancelled, booking_status="CANCELLED")
    assert cancelled["refunded_amount"] == 33915
    assert_charge_identity(cancelled)

    assert_segment_state(
        workbench.read_segment(state["segment1_id"]), status="RELEASED"
    )
    assert_segment_state(
        workbench.read_segment(state["segment2_id"]), status="RELEASED"
    )
    assert_flight_leg_state(
        workbench.read_leg(state["leg1_id"]), booked_checked_count=0
    )
    assert_flight_leg_state(
        workbench.read_leg(state["leg2_id"]), booked_checked_count=0
    )


def test_cancellation_discount_is_taken_on_the_post_refund_base(
    api, workbench, two_leg_confirmed_booking
):
    """The refund does not shrink the tier selection, only the base the discount is
    computed on, so the two steps read different amounts.

    PRD §3.8: "`net_payable_amount` is `subtotal_amount` minus `refunded_amount`
    minus `loyalty_discount_amount`."

    Design: Difficulty/compensating_invariant/reservation_money_identity_survives_cancellation_refund
    """
    state = two_leg_confirmed_booking()
    workbench.sweep_irops(state["leg1_id"])
    workbench.sweep_irops(state["leg1_id"])
    workbench.cancel_reservation(state["reservation_id"])

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        reservation,
        subtotal_amount=67830,
        irops_fee_total=7000,
        loyalty_tier_pct=0.05,
        loyalty_discount_amount=1696,
        refunded_amount=33915,
        net_payable_amount=32219,
    )
    assert_charge_identity(reservation)

    summary = workbench.read_charge_summary(state["reservation_id"])
    assert summary["refunded_amount"] == 33915
    assert summary["net_payable_amount"] == 32219
    assert summary["invariant_holds"] is True


def test_charge_summary_reports_invariant_holds_true(
    api, workbench, confirmed_booking, compliance_officer_headers
):
    """The charge summary is a computed read: it reports the balanced identity and
    writes nothing to the reservation it summarises.

    PRD §3.8: "A computed charge-summary read is available on any reservation and
    returns its `reservation_id`, `subtotal_amount`, `irops_fee_total`,
    `loyalty_tier_pct`, `loyalty_discount_amount`, `refunded_amount`,
    `net_payable_amount` and a boolean `invariant_holds` reporting whether that
    identity currently balances."

    Design: Corner/endpoints/charge_summary_reports_invariant_holds_true
    """
    state = confirmed_booking()
    before = workbench.read_reservation(state["reservation_id"])

    summary = validate_success(
        api.get_reservation_charge_summary(
            state["reservation_id"], compliance_officer_headers
        )
    )
    assert summary["reservation_id"] == state["reservation_id"]
    assert summary["subtotal_amount"] == 33180
    assert summary["irops_fee_total"] == 0
    assert summary["loyalty_tier_pct"] == 0
    assert summary["loyalty_discount_amount"] == 0
    assert summary["refunded_amount"] == 0
    assert summary["net_payable_amount"] == 33180
    assert summary["invariant_holds"] is True

    after = workbench.read_reservation(state["reservation_id"])
    assert after["version"] == before["version"]
    assert_charge_identity(after)


def test_irops_care_sweep_charges_a_fee_per_affected_animal(
    api, workbench, confirmed_booking
):
    """The sweep prices care per held animal, leaves the segment fee alone and does
    not itself change the leg's status.

    PRD §3.8: "For every reservation owning a slot on that leg in `RESERVED` or
    `ACCEPTED`, the reservation's `irops_fee_total` is incremented by 3500 minor
    units for each such animal, the charge assembly re-runs — which may push the
    reservation across a loyalty tier boundary — and the reservation's `version`
    increments by one."

    Design: Corner/endpoints/irops_care_sweep_charges_a_fee_per_affected_animal
    """
    state = confirmed_booking()

    sweep = get_success_data(
        api.create_irops_care_sweep(
            {"flight_leg_id": state["leg_id"]}, workbench.acceptance()
        )
    )
    assert sweep["flight_leg_id"] == state["leg_id"]
    assert sweep["affected_animal_count"] == 1
    assert sweep["irops_fee_per_animal"] == 3500
    assert sweep["total_fee_charged"] == 3500

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        reservation,
        subtotal_amount=36680,
        irops_fee_total=3500,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        refunded_amount=0,
        net_payable_amount=36680,
    )
    assert_segment_state(
        workbench.read_segment(state["segment_id"]), segment_fee_amount=33180
    )
    assert workbench.read_leg(state["leg_id"])["status"] == "SCHEDULED"


def test_repeat_irops_care_sweep_charges_again(api, workbench, confirmed_booking):
    """A second disruption is a second round of care, so the sweep is deliberately
    repeatable and the fees accumulate.

    PRD §3.8: "The sweep is deliberately **repeatable**: calling it again for the
    same leg charges again, because a second disruption incurs a second round of
    care."

    Design: Corner/endpoints/repeat_irops_care_sweep_charges_again
    """
    state = confirmed_booking()
    workbench.sweep_irops(state["leg_id"])

    second = get_success_data(
        api.create_irops_care_sweep(
            {"flight_leg_id": state["leg_id"]}, workbench.acceptance()
        )
    )
    assert second["affected_animal_count"] == 1
    assert second["total_fee_charged"] == 3500

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        reservation,
        subtotal_amount=40180,
        irops_fee_total=7000,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        refunded_amount=0,
        net_payable_amount=40180,
    )
    assert_charge_identity(reservation)
