"""Optimistic concurrency on the leg pool and gates that read a sibling row's state.

Slot creation is guarded by the leg's version, and two transitions — confirming a
reservation and departing a leg — are gated on the aggregate state of rows the
caller does not name in the request.
"""

from test_helpers import (
    ApiErrorId,
    SECOND_ACCEPTANCE_AGENT_ID,
    assert_animal_state,
    assert_charge_identity,
    assert_flight_leg_state,
    assert_reservation_money,
    assert_reservation_state,
    assert_segment_state,
    validate_error,
    validate_success,
)


def _two_animal_booking(workbench, catalog, primary_leg, *, promote_all: bool):
    """One CHECKED reservation carrying two animals, each holding a slot at
    sequence index 1 on AN101, with both animals' paperwork verified."""
    leg = primary_leg()
    reservation = workbench.create_reservation()
    first_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    second_animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
    )
    first_slot = workbench.create_segment(
        first_animal["id"], leg["id"], sequence_index=1
    )
    second_slot = workbench.create_segment(
        second_animal["id"], leg["id"], sequence_index=1
    )
    workbench.screen_animal(first_animal["id"])
    workbench.screen_animal(second_animal["id"])
    workbench.verified_document(first_animal["id"])
    workbench.verified_document(second_animal["id"])
    workbench.verify_compliance(reservation["id"])
    workbench.mark_travel_ready(first_animal["id"])
    if promote_all:
        workbench.mark_travel_ready(second_animal["id"])
    return {
        "leg_id": leg["id"],
        "reservation_id": reservation["id"],
        "first_animal_id": first_animal["id"],
        "second_animal_id": second_animal["id"],
        "first_slot_id": first_slot["id"],
        "second_slot_id": second_slot["id"],
    }


def test_segment_create_with_stale_flight_leg_version_rejected(
    api, workbench, catalog, primary_leg
):
    """A forecast update advances the leg's version, so a slot request quoting the
    version the client first observed is refused before it can oversubscribe the leg.

    PRD §2.9: "If `expected_flight_leg_version` does not equal the leg's current
    `version`, the create is refused with `ERR_STALE_FLIGHT_LEG_VERSION` (HTTP 412)
    rather than being allowed to oversubscribe the leg."

    Design: Corner/cross_cutting_complexity_layers/segment_create_with_stale_flight_leg_version_rejected
    """
    leg = primary_leg()
    observed_version = leg["version"]
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )

    reforecast = workbench.update_forecast(leg["id"], 26.0, 16.0)
    assert reforecast["version"] == observed_version + 1

    stale = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 1,
            "expected_flight_leg_version": observed_version,
        },
        workbench.agent(),
    )
    validate_error(stale, ApiErrorId.STALE_FLIGHT_LEG_VERSION, 412)
    assert_flight_leg_state(
        workbench.read_leg(leg["id"]), posture="OPEN", booked_checked_count=0
    )

    accepted = validate_success(
        api.create_segment_assignment(
            {
                "animal_record_id": animal["id"],
                "flight_leg_id": leg["id"],
                "routing_type": "CHECKED",
                "sequence_index": 1,
                "expected_flight_leg_version": workbench.leg_version(leg["id"]),
            },
            workbench.agent(),
        ),
        201,
    )
    assert_segment_state(accepted, status="RESERVED")
    assert_flight_leg_state(
        workbench.read_leg(leg["id"]), booked_checked_count=1
    )


def test_flight_leg_version_increments_on_every_write(api, workbench, primary_leg):
    """Creation starts the version at one and each subsequent write adds exactly one,
    while reads add nothing.

    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation of the row, and `version`, an integer that starts at 1 on
    creation and increments by exactly one on every mutation of the row."

    Design: Corner/cross_cutting_complexity_layers/flight_leg_version_increments_on_every_write
    """
    leg = primary_leg()
    assert leg["version"] == 1

    reforecast = workbench.update_forecast(leg["id"], 26.0, 16.0)
    assert reforecast["version"] == 2

    delayed = workbench.delay_leg(
        leg["id"], "2026-09-10T04:00:00Z", "2026-09-10T18:00:00Z"
    )
    assert delayed["version"] == 3

    restored = workbench.restore_leg(
        leg["id"], "2026-09-10T02:00:00Z", "2026-09-10T15:00:00Z"
    )
    assert restored["version"] == 4
    assert_flight_leg_state(restored, status="SCHEDULED", block_minutes=780)

    first_read = workbench.read_leg(leg["id"])
    second_read = workbench.read_leg(leg["id"])
    assert first_read["version"] == 4
    assert second_read["version"] == 4


def test_confirm_response_reflects_the_cascade_in_the_same_response(
    api, workbench, travel_ready_booking, compliance_officer_headers
):
    """The confirmation response already carries the re-run charge assembly, and an
    immediate read returns exactly the same row without any settling step.

    PRD §3.4: "In all three cases the reservation moves to `CONFIRMED`, the charge
    assembly re-runs and the reservation's `version` increments by one".

    Design: Corner/consistency_model/confirm_response_reflects_the_cascade_in_the_same_response
    """
    state = travel_ready_booking()

    confirmed = validate_success(
        api.confirm_reservation(state["reservation_id"], workbench.agent())
    )
    assert_reservation_state(
        confirmed, booking_status="CONFIRMED", compliance_status="VERIFIED"
    )
    assert_reservation_money(
        confirmed,
        subtotal_amount=33180,
        irops_fee_total=0,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        refunded_amount=0,
        net_payable_amount=33180,
    )
    assert_charge_identity(confirmed)

    immediately = workbench.read_reservation(state["reservation_id"])
    assert immediately["version"] == confirmed["version"]
    assert immediately["booking_status"] == "CONFIRMED"
    assert immediately["subtotal_amount"] == confirmed["subtotal_amount"]
    assert immediately["net_payable_amount"] == confirmed["net_payable_amount"]

    summary = validate_success(
        api.get_reservation_charge_summary(
            state["reservation_id"], compliance_officer_headers
        )
    )
    assert summary["net_payable_amount"] == 33180
    assert summary["invariant_holds"] is True

    assert_animal_state(
        workbench.read_animal(state["animal_id"]), status="TRAVEL_READY"
    )
    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="RESERVED",
        segment_fee_amount=33180,
    )


def test_reservation_confirm_blocked_by_sibling_animal_state_rejected(
    api, workbench, catalog, primary_leg
):
    """Confirmation reads every animal of the booking, so one sibling left in
    `SCREENED` blocks it even though the compliance dimension is verified.

    PRD §3.4: "From `PENDING`, the reservation's `compliance_status` must be `VERIFIED`,
    its `animal_count` must be at least 1, every animal whose `status` is not `DENIED`
    must be `TRAVEL_READY`, and every such animal must hold at least one routing slot in
    `RESERVED`."

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_blocked_by_sibling_animal_state_rejected
    """
    state = _two_animal_booking(workbench, catalog, primary_leg, promote_all=False)
    assert_animal_state(
        workbench.read_animal(state["first_animal_id"]), status="TRAVEL_READY"
    )
    assert_animal_state(
        workbench.read_animal(state["second_animal_id"]), status="SCREENED"
    )

    refused = api.confirm_reservation(state["reservation_id"], workbench.agent())
    validate_error(refused, ApiErrorId.ANIMAL_INVALID_STATE, 409)

    unchanged = workbench.read_reservation(state["reservation_id"])
    assert_reservation_state(
        unchanged, booking_status="PENDING", compliance_status="VERIFIED"
    )
    assert unchanged["animal_count"] == 2


def test_confirm_succeeds_once_every_sibling_animal_is_travel_ready(
    api, workbench, catalog, primary_leg
):
    """Promoting the remaining sibling satisfies the aggregate gate, and the two slots
    together carry the booking into the mid loyalty tier.

    PRD §3.8: "`subtotal_amount` is the sum of `segment_fee_amount` over **every** slot
    belonging to **every** animal record of the reservation, in **any** status"

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_blocked_by_sibling_animal_state_rejected
    """
    state = _two_animal_booking(workbench, catalog, primary_leg, promote_all=True)

    confirmed = validate_success(
        api.confirm_reservation(state["reservation_id"], workbench.agent())
    )
    assert_reservation_state(confirmed, booking_status="CONFIRMED")
    assert confirmed["animal_count"] == 2
    assert_reservation_money(
        confirmed,
        subtotal_amount=66360,
        irops_fee_total=0,
        loyalty_tier_pct=0.05,
        loyalty_discount_amount=3318,
        refunded_amount=0,
        net_payable_amount=63042,
    )
    assert_charge_identity(confirmed)

    assert_segment_state(
        workbench.read_segment(state["first_slot_id"]), segment_fee_amount=33180
    )
    assert_segment_state(
        workbench.read_segment(state["second_slot_id"]), segment_fee_amount=33180
    )


def test_leg_depart_blocked_by_unaccepted_child_segment_rejected(
    api, workbench, catalog, primary_leg
):
    """The leg's own transition is gated on its children: one slot still `RESERVED`
    stops the departure even though the other one has been accepted.

    PRD §3.7: "The leg's `posture` must not be `EMBARGOED` (`ERR_LEG_EMBARGOED`), no
    slot on the leg may remain in `RESERVED` (`ERR_LEG_HAS_UNACCEPTED_SEGMENTS`), and
    every slot on the leg in `ACCEPTED` must have a `completed_welfare_check_count` of at
    least its `required_welfare_check_count` (`ERR_WELFARE_CHECKS_INCOMPLETE`)."

    Design: Difficulty/cross_entity_state_dependency/leg_depart_blocked_by_unaccepted_child_segment_rejected
    """
    state = _two_animal_booking(workbench, catalog, primary_leg, promote_all=True)
    workbench.confirm_reservation(state["reservation_id"])
    workbench.amend_animal(state["first_animal_id"], measured_weight_kg=27)
    workbench.accept_segment(
        state["first_slot_id"], as_user_id=SECOND_ACCEPTANCE_AGENT_ID
    )

    refused = api.depart_flight_leg(
        state["leg_id"], workbench.acceptance(SECOND_ACCEPTANCE_AGENT_ID)
    )
    validate_error(refused, ApiErrorId.LEG_HAS_UNACCEPTED_SEGMENTS, 422)

    assert_flight_leg_state(
        workbench.read_leg(state["leg_id"]),
        status="SCHEDULED",
        booked_checked_count=2,
    )
    assert_segment_state(
        workbench.read_segment(state["first_slot_id"]), status="ACCEPTED"
    )
    assert_segment_state(
        workbench.read_segment(state["second_slot_id"]), status="RESERVED"
    )


def test_leg_departs_once_every_child_segment_is_accepted(
    api, workbench, catalog, primary_leg
):
    """With both slots accepted the aggregate gate is satisfied, and departure moves the
    animals and their booking together.

    PRD §3.7: "On success the leg moves to `DEPARTED`, every animal holding an
    `ACCEPTED` slot on the leg moves `TRAVEL_READY → IN_TRANSIT`, every reservation
    owning such an animal moves `CONFIRMED → IN_TRANSIT`, posture derivation writes
    `CLOSED`, and the leg's `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/leg_depart_blocked_by_unaccepted_child_segment_rejected
    """
    state = _two_animal_booking(workbench, catalog, primary_leg, promote_all=True)
    workbench.confirm_reservation(state["reservation_id"])
    workbench.amend_animal(state["first_animal_id"], measured_weight_kg=27)
    workbench.amend_animal(state["second_animal_id"], measured_weight_kg=27)
    workbench.accept_segment(
        state["first_slot_id"], as_user_id=SECOND_ACCEPTANCE_AGENT_ID
    )
    workbench.accept_segment(
        state["second_slot_id"], as_user_id=SECOND_ACCEPTANCE_AGENT_ID
    )

    departed = validate_success(
        api.depart_flight_leg(
            state["leg_id"], workbench.acceptance(SECOND_ACCEPTANCE_AGENT_ID)
        )
    )
    assert_flight_leg_state(departed, status="DEPARTED", posture="CLOSED")

    assert_animal_state(
        workbench.read_animal(state["first_animal_id"]), status="IN_TRANSIT"
    )
    assert_animal_state(
        workbench.read_animal(state["second_animal_id"]), status="IN_TRANSIT"
    )
    assert_reservation_state(
        workbench.read_reservation(state["reservation_id"]),
        booking_status="IN_TRANSIT",
    )
