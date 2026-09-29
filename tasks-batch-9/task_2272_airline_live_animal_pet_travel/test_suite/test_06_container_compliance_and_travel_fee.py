"""Exact-fit container evaluation and the two variants of the travel fee.

The fee is built in four pinned steps with two ordered multipliers, and the
provisional and final variants differ in exactly one input, so the same slot
carries two different prices at two different moments of its life.
"""

from test_helpers import (
    SECOND_ACCEPTANCE_AGENT_ID,
    assert_animal_state,
    assert_charge_identity,
    assert_reservation_money,
    assert_segment_state,
    validate_success,
)


def _snub_nosed_cargo_itinerary(workbench, catalog, primary_leg, connecting_leg):
    """Book one snub-nosed dog in the hold across a long-haul leg and a short one."""
    workbench.create_breed_restriction(
        catalog["species_id"], breed_name="Bulldog", restriction_type="SNUB_NOSED"
    )
    long_haul = primary_leg()
    short_leg = connecting_leg()
    reservation = workbench.create_reservation(
        passenger_name="Chan", contact_email="chan@example.com", routing_type="CARGO"
    )
    animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Bao",
        breed_name="Bulldog",
        declared_weight_kg=20,
    )
    first = workbench.create_segment(
        animal["id"], long_haul["id"], routing_type="CARGO", sequence_index=1
    )
    second = workbench.create_segment(
        animal["id"], short_leg["id"], routing_type="CARGO", sequence_index=2
    )
    return {
        "reservation_id": reservation["id"],
        "animal_id": animal["id"],
        "long_haul": long_haul,
        "short_leg": short_leg,
        "first_segment_id": first["id"],
        "second_segment_id": second["id"],
        "first_segment": first,
        "second_segment": second,
    }


def test_container_exactly_meeting_every_requirement_is_compliant(
    api, workbench, catalog
):
    """A container that sits exactly on all four thresholds passes them all; one
    centimetre of interior height below the threshold fails the first of them.

    PRD §3.4: "All four dimensional comparisons are strict, so a container that
    exactly meets a requirement passes it."

    Design: Corner/calculations/container_exactly_meeting_every_requirement_is_compliant
    """
    exact = workbench.create_container(
        model_code="K9-EXACT",
        interior_length_cm=58,
        interior_width_cm=40,
        interior_height_cm=43,
        tare_weight_kg=7,
        ventilation_area_pct=14,
        ventilated_side_count=3,
    )
    reservation = workbench.create_reservation()
    on_exact = workbench.create_animal(
        reservation["id"], catalog["species_id"], exact["id"]
    )

    screened = validate_success(
        api.screen_animal_record(on_exact["id"], workbench.acceptance())
    )
    assert_animal_state(
        screened,
        status="SCREENED",
        container_compliance_state="COMPLIANT",
        deficiency_codes=[],
        chargeable_weight_kg=27,
    )

    one_short = workbench.create_container(
        model_code="K9-H42",
        interior_length_cm=58,
        interior_width_cm=40,
        interior_height_cm=42,
        tare_weight_kg=7,
        ventilation_area_pct=14,
        ventilated_side_count=3,
    )
    on_short = workbench.create_animal(
        reservation["id"], catalog["species_id"], one_short["id"], animal_name="Taro"
    )
    deficient = validate_success(
        api.screen_animal_record(on_short["id"], workbench.acceptance())
    )
    assert_animal_state(
        deficient,
        status="SCREENED",
        container_compliance_state="DEFICIENT",
        deficiency_codes=["HEIGHT"],
        chargeable_weight_kg=27,
    )


def test_travel_fee_provisional_and_final_variants_diverge_on_the_same_slot(
    api, workbench, confirmed_booking
):
    """The same slot is priced twice from two different weight bases, and the
    heavier measured weight crosses the second marginal rate band.

    PRD §3.8: "The provisional variant, `PROVISIONAL_AT_RESERVATION`, runs at
    screening time before the animal is physically weighed and takes its weight
    basis from `declared_weight_kg`; it rewrites every slot of the animal that is
    `RESERVED` and stamps `fee_variant` as `PROVISIONAL_AT_RESERVATION` on each. The
    final variant, `FINAL_AT_ACCEPTANCE`, runs when the animal is on the scale at
    the counter and takes its weight basis from `measured_weight_kg`; it rewrites
    only the slot being accepted and stamps that slot's `fee_variant` as
    `FINAL_AT_ACCEPTANCE`."

    Design: Difficulty/dual_variant_calc/travel_fee_provisional_vs_final_diverges_on_same_segment
    """
    state = confirmed_booking()

    provisional = workbench.read_segment(state["segment_id"])
    assert_segment_state(
        provisional,
        status="RESERVED",
        segment_fee_amount=33180,
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )
    assert_animal_state(
        workbench.read_animal(state["animal_id"]), chargeable_weight_kg=27
    )

    workbench.amend_animal(state["animal_id"], measured_weight_kg=27)
    accepted = validate_success(
        api.accept_segment_assignment(
            state["segment_id"], workbench.acceptance(SECOND_ACCEPTANCE_AGENT_ID)
        )
    )
    assert_segment_state(
        accepted,
        status="ACCEPTED",
        segment_fee_amount=37560,
        fee_variant="FINAL_AT_ACCEPTANCE",
    )
    assert_animal_state(
        workbench.read_animal(state["animal_id"]), chargeable_weight_kg=34
    )


def test_travel_fee_final_variant_repricing_flows_into_reservation_money(
    api, workbench, accepted_booking
):
    """Repricing one slot at the counter re-runs the whole charge assembly, and the
    money identity still balances afterwards.

    PRD §3.7: "On success the slot's `status` becomes `ACCEPTED`, the travel fee runs
    in its final variant over **this slot only**, `AnimalRecord.chargeable_weight_kg`
    is recomputed from `measured_weight_kg`, the charge assembly re-runs, and the
    slot's `version` increments by one."

    Design: Difficulty/dual_variant_calc/travel_fee_provisional_vs_final_diverges_on_same_segment
    """
    state = accepted_booking(measured_weight_kg=27)

    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="ACCEPTED",
        segment_fee_amount=37560,
        fee_variant="FINAL_AT_ACCEPTANCE",
    )

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        reservation,
        subtotal_amount=37560,
        irops_fee_total=0,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        refunded_amount=0,
        net_payable_amount=37560,
    )
    assert_charge_identity(reservation)

    summary = workbench.read_charge_summary(state["reservation_id"])
    assert summary["subtotal_amount"] == 37560
    assert summary["net_payable_amount"] == 37560
    assert summary["invariant_holds"] is True


def test_snub_nosed_cargo_fee_rounds_each_segment_before_summing(
    api, workbench, catalog, primary_leg, connecting_leg
):
    """The snub-nosed multiplier is rounded where it is applied, so the long-haul
    multiplier compounds an already-rounded amount rather than a raw product.

    PRD §3.8: "If the animal's breed is snub-nosed and the slot's `routing_type` is
    not `CABIN`, the fee is multiplied by one and fifteen hundredths and rounded half
    up to whole minor units. If the leg's `block_minutes` is strictly greater than
    eight hours and the animal's `animal_kind` is `PET`, the resulting fee is
    multiplied by one and two tenths and rounded half up to whole minor units; a
    `SERVICE_ANIMAL` never attracts the long-haul multiplier."

    Design: Difficulty/combinatorial_formula/snub_nosed_cargo_fee_rounds_per_segment_before_summing
    """
    state = _snub_nosed_cargo_itinerary(
        workbench, catalog, primary_leg, connecting_leg
    )

    assert_segment_state(
        workbench.read_segment(state["first_segment_id"]),
        status="RESERVED",
        segment_fee_amount=48508,
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )
    assert_segment_state(
        workbench.read_segment(state["second_segment_id"]),
        status="RESERVED",
        segment_fee_amount=40423,
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )
    assert workbench.read_leg(state["long_haul"]["id"])["block_minutes"] == 780
    assert workbench.read_leg(state["short_leg"]["id"])["block_minutes"] == 300


def test_snub_nosed_cargo_subtotal_sums_already_rounded_segment_fees(
    api, workbench, catalog, primary_leg, connecting_leg
):
    """Summing the two rounded segment fees puts the booking over the mid loyalty
    threshold, and the discount is taken at the single rounding point.

    PRD §3.8: "Fourth — and this is the rounding order that must not be inverted —
    the reservation's segment total is the sum of the already-rounded
    `segment_fee_amount` values across every slot of the reservation in any status."

    Design: Difficulty/combinatorial_formula/snub_nosed_cargo_fee_rounds_per_segment_before_summing
    """
    state = _snub_nosed_cargo_itinerary(
        workbench, catalog, primary_leg, connecting_leg
    )

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_money(
        reservation,
        subtotal_amount=88931,
        irops_fee_total=0,
        loyalty_tier_pct=0.05,
        loyalty_discount_amount=4447,
        refunded_amount=0,
        net_payable_amount=84484,
    )
    assert_charge_identity(reservation)

    summary = workbench.read_charge_summary(state["reservation_id"])
    assert summary["subtotal_amount"] == 88931
    assert summary["loyalty_discount_amount"] == 4447
    assert summary["net_payable_amount"] == 84484
    assert summary["invariant_holds"] is True
