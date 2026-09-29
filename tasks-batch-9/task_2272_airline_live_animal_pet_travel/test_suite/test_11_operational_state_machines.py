"""Lifecycle edges: initial states, schedule recovery, arrival and embargo release.

Each entity's lifecycle is declared with its permitted edges and its terminal
states, and an operation attempted from a status that does not permit it is
refused rather than silently ignored.
"""

from test_helpers import (
    ApiErrorId,
    SECOND_ACCEPTANCE_AGENT_ID,
    assert_animal_state,
    assert_flight_leg_state,
    assert_initial_version,
    assert_reservation_money,
    assert_reservation_state,
    assert_segment_state,
    health_document_payload,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_flight_leg_delay_then_restore_returns_to_scheduled(
    api, workbench, primary_leg
):
    """The delay-and-restore loop recovers the schedule exactly, including the derived
    block minutes, and each write leaves its mark on the version.

    PRD §3.3: "The leg moves `DELAYED → SCHEDULED`, both instants and `block_minutes`
    are restored to the supplied values, `connection_minutes` and
    `required_welfare_check_count` are recomputed for downstream slots in `RESERVED` or
    `ACCEPTED`, embargo determination and posture derivation re-run, and the leg's
    `version` increments by one."

    Design: Corner/state_machines/flight_leg_delay_then_restore_returns_to_scheduled
    """
    leg = primary_leg()

    delayed = workbench.delay_leg(
        leg["id"], "2026-09-10T04:00:00Z", "2026-09-10T17:00:00Z"
    )
    assert delayed["status"] == "DELAYED"
    assert delayed["block_minutes"] == 780

    restored = workbench.restore_leg(
        leg["id"], "2026-09-10T02:00:00Z", "2026-09-10T15:00:00Z"
    )
    assert_flight_leg_state(
        restored,
        status="SCHEDULED",
        posture="OPEN",
        governing_embargo_rule_id=None,
        block_minutes=780,
    )
    assert restored["scheduled_departure_utc"] == "2026-09-10T02:00:00Z"
    assert restored["scheduled_arrival_utc"] == "2026-09-10T15:00:00Z"
    assert restored["version"] == 3


def test_flight_leg_restore_schedule_from_scheduled_rejected(
    api, workbench, primary_leg
):
    """A restore is only meaningful from `DELAYED`, and the state rung answers above
    the monotonicity rung the same request also breaks.

    PRD §3.3: "Any attempt to delay, restore, cancel, depart, arrive, re-forecast a
    leg, or reserve a slot on it, when the leg's `status` does not permit that
    operation, is refused with `ERR_FLIGHT_LEG_INVALID_STATE`."

    Design: Corner/state_machines/flight_leg_restore_schedule_from_scheduled_rejected
    """
    leg = primary_leg()

    refused = api.restore_flight_leg_schedule(
        leg["id"],
        {
            "restored_departure_utc": "2026-09-10T04:00:00Z",
            "restored_arrival_utc": "2026-09-10T18:00:00Z",
        },
        workbench.admin(),
    )
    validate_error(refused, ApiErrorId.FLIGHT_LEG_INVALID_STATE, 409)

    unchanged = workbench.read_leg(leg["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["scheduled_departure_utc"] == "2026-09-10T02:00:00Z"
    assert_initial_version(unchanged)


def test_newly_created_rows_start_in_their_declared_initial_states(
    api, workbench, catalog, primary_leg
):
    """Every row of the booking chain lands on its declared initial state, and the
    freshly submitted document is the last of them.

    PRD §3.6: "The document is written with `status` `SUBMITTED`, `revision_count` 0
    and `reviewed_by_user_id` null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    leg = primary_leg()
    assert_flight_leg_state(leg, status="SCHEDULED", posture="OPEN")

    reservation = workbench.create_reservation()
    assert_reservation_state(
        reservation, booking_status="PENDING", compliance_status="UNVERIFIED"
    )

    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    assert_animal_state(
        animal, status="DRAFT", container_compliance_state="UNEVALUATED"
    )

    segment = workbench.create_segment(animal["id"], leg["id"])
    assert_segment_state(
        segment, status="RESERVED", fee_variant="PROVISIONAL_AT_RESERVATION"
    )

    document = validate_success(
        api.create_health_document(
            health_document_payload(animal["id"]), workbench.agent()
        ),
        201,
    )
    assert document["status"] == "SUBMITTED"
    assert document["revision_count"] == 0
    assert document["reviewed_by_user_id"] is None
    assert_initial_version(document)


def test_cancelled_reservation_cannot_be_confirmed(api, workbench, catalog, primary_leg):
    """`CANCELLED` is terminal on the commercial dimension, so a cancelled booking is
    refused confirmation while its refund stands.

    PRD §3.4: "In all three cases the reservation moves to `CONFIRMED`, the charge
    assembly re-runs and the reservation's `version` increments by one; a
    `compliance_status` other than `VERIFIED` is refused with
    `ERR_COMPLIANCE_NOT_VERIFIED`, and a `booking_status` outside the permitted set
    with `ERR_RESERVATION_INVALID_STATE`."

    Design: Corner/state_machines/cancelled_reservation_cannot_be_confirmed
    """
    leg = primary_leg()
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    segment = workbench.create_segment(animal["id"], leg["id"])

    cancelled = validate_success(
        api.cancel_reservation(
            reservation["id"], workbench.agent(), {"reason": "passenger withdrew"}
        )
    )
    assert_reservation_state(cancelled, booking_status="CANCELLED")

    refused = api.confirm_reservation(reservation["id"], workbench.agent())
    validate_error(refused, ApiErrorId.RESERVATION_INVALID_STATE, 409)

    assert_reservation_money(
        workbench.read_reservation(reservation["id"]),
        subtotal_amount=33180,
        refunded_amount=16590,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        net_payable_amount=16590,
    )
    assert_segment_state(workbench.read_segment(segment["id"]), status="RELEASED")
    assert_flight_leg_state(workbench.read_leg(leg["id"]), booked_checked_count=0)


def test_repeat_screen_on_already_screened_animal_rejected(
    api, workbench, screened_booking
):
    """Screening runs from `DRAFT` or from `TRAVEL_READY`, so a second screen of a
    screened animal is refused and nothing is recomputed.

    PRD §2.6: "The animal record's `status` permits the requested operation —
    otherwise `ERR_ANIMAL_INVALID_STATE` (409). The permitted sets are `DRAFT` or
    `TRAVEL_READY` for screening; `SCREENED` for marking travel-ready".

    Design: Corner/state_machines/repeat_screen_on_already_screened_animal_rejected
    """
    state = screened_booking()

    refused = api.screen_animal_record(state["animal_id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.ANIMAL_INVALID_STATE, 409)

    assert_animal_state(
        workbench.read_animal(state["animal_id"]),
        status="SCREENED",
        container_compliance_state="COMPLIANT",
        chargeable_weight_kg=27,
    )
    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="RESERVED",
        segment_fee_amount=33180,
        fee_variant="PROVISIONAL_AT_RESERVATION",
    )


def test_mark_travel_ready_with_deficient_container_rejected(
    api, workbench, catalog
):
    """A container that is too short for the animal to stand blocks promotion on the
    very first gate.

    PRD §3.4: "The animal's `container_compliance_state` must be `COMPLIANT`, and a
    `DEFICIENT` or `UNEVALUATED` state is refused with `ERR_CONTAINER_NON_COMPLIANT`."

    Design: Corner/state_machines/mark_travel_ready_with_deficient_container_rejected
    """
    short_container = workbench.create_container(
        model_code="K9-SHORT",
        interior_length_cm=60,
        interior_width_cm=40,
        interior_height_cm=30,
    )
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], short_container["id"]
    )
    screened = workbench.screen_animal(animal["id"])
    assert_animal_state(
        screened,
        status="SCREENED",
        container_compliance_state="DEFICIENT",
        deficiency_codes=["HEIGHT"],
        chargeable_weight_kg=27,
    )

    refused = api.mark_animal_record_travel_ready(animal["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.CONTAINER_NON_COMPLIANT, 422)

    assert_animal_state(
        workbench.read_animal(animal["id"]),
        status="SCREENED",
        container_compliance_state="DEFICIENT",
        deficiency_codes=["HEIGHT"],
    )


def test_service_animal_without_behavior_attestation_rejected(
    api, workbench, catalog, primary_leg
):
    """Service animal policy substitutes the behaviour attestation for the paperwork
    gate, so a missing attestation is what blocks promotion.

    PRD §3.4: "when the animal is a `SERVICE_ANIMAL`, its
    `behavior_attestation_on_file` must be true, a false attestation being refused with
    `ERR_BEHAVIOR_ATTESTATION_MISSING`, and the import-document gate does not apply".

    Design: Corner/state_machines/service_animal_without_behavior_attestation_rejected
    """
    cabin_container = workbench.create_container(
        model_code="CABIN-S",
        interior_length_cm=35,
        interior_width_cm=25,
        interior_height_cm=28,
        tare_weight_kg=2,
        ventilation_area_pct=10,
        ventilated_side_count=2,
        wheels_removable=True,
        cabin_eligible=True,
    )
    leg = primary_leg()
    reservation = workbench.create_reservation(
        passenger_name="Ng",
        contact_email="ng@example.com",
        routing_type="CABIN",
        is_service_animal_booking=True,
    )
    animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        cabin_container["id"],
        animal_name="Kai",
        breed_name="Poodle",
        animal_kind="SERVICE_ANIMAL",
        declared_weight_kg=8,
        height_at_shoulder_cm=20,
        length_nose_to_tail_cm=30,
        age_weeks=40,
    )
    workbench.create_segment(
        animal["id"], leg["id"], routing_type="CABIN", sequence_index=1
    )
    screened = workbench.screen_animal(animal["id"])
    assert_animal_state(screened, container_compliance_state="COMPLIANT")

    refused = api.mark_animal_record_travel_ready(animal["id"], workbench.acceptance())
    validate_error(refused, ApiErrorId.BEHAVIOR_ATTESTATION_MISSING, 422)

    workbench.amend_animal(animal["id"], behavior_attestation_on_file=True)
    promoted = validate_success(
        api.mark_animal_record_travel_ready(animal["id"], workbench.acceptance())
    )
    assert_animal_state(promoted, status="TRAVEL_READY")


def test_arrive_completes_segment_delivers_animal_and_completes_reservation(
    api, workbench, departed_booking
):
    """Arrival cascades upward through the slot and the animal into the booking, and
    the money is settled one final time.

    PRD §3.7: "Then the completion bubbles up: a reservation every one of whose animals
    with a `status` other than `DENIED` is `DELIVERED` moves `IN_TRANSIT → COMPLETED`,
    and the charge assembly runs one final time."

    Design: Corner/state_machines/arrive_completes_segment_delivers_animal_and_completes_reservation
    """
    state = departed_booking(measured_weight_kg=27)

    arrived = validate_success(
        api.arrive_flight_leg(
            state["leg_id"], workbench.acceptance(SECOND_ACCEPTANCE_AGENT_ID)
        )
    )
    assert_flight_leg_state(arrived, status="ARRIVED", posture="CLOSED")

    assert_segment_state(
        workbench.read_segment(state["segment_id"]), status="COMPLETED"
    )
    assert_animal_state(workbench.read_animal(state["animal_id"]), status="DELIVERED")

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_state(reservation, booking_status="COMPLETED")
    assert_reservation_money(
        reservation,
        subtotal_amount=37560,
        refunded_amount=0,
        net_payable_amount=37560,
    )


def test_embargo_releases_reserved_segment_but_leaves_accepted_segment_alone(
    api, workbench, accepted_booking
):
    """A forecast update that embargoes the leg releases only the slots still merely
    reserved; the accepted slot and its booking are untouched.

    PRD §3.3: "If the posture becomes `EMBARGOED`, the service immediately releases
    every routing slot on the leg that is still `RESERVED` and whose `routing_type` is
    contained in the governing rule's `applies_to_routings` — slots in a routing the
    rule does not suppress are left alone."

    Design: Corner/state_machines/embargo_releases_reserved_segment_but_leaves_accepted_segment_alone
    """
    state = accepted_booking(measured_weight_kg=27)
    catalog = state["catalog"]

    second_reservation = workbench.create_reservation(
        passenger_name="Lam", contact_email="lam@example.com"
    )
    second_animal = workbench.create_animal(
        second_reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
        breed_name="Beagle",
        declared_weight_kg=20,
        height_at_shoulder_cm=35,
        length_nose_to_tail_cm=50,
        age_weeks=52,
    )
    second_segment = workbench.create_segment(second_animal["id"], state["leg_id"])
    assert_flight_leg_state(
        workbench.read_leg(state["leg_id"]), booked_checked_count=2
    )

    rule = workbench.create_embargo_rule(
        catalog["hkg_id"],
        forecast_high_limit_c=29.5,
        forecast_low_limit_c=-5.0,
        applies_to_routings=["CHECKED", "CARGO"],
    )
    embargoed = workbench.update_forecast(state["leg_id"], 30.0, 20.0)
    assert_flight_leg_state(
        embargoed,
        posture="EMBARGOED",
        governing_embargo_rule_id=rule["id"],
        booked_checked_count=1,
    )

    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="ACCEPTED",
        segment_fee_amount=37560,
    )
    assert_segment_state(
        workbench.read_segment(second_segment["id"]), status="RELEASED"
    )

    assert_reservation_state(
        workbench.read_reservation(state["reservation_id"]),
        booking_status="CONFIRMED",
    )
    assert_reservation_money(
        workbench.read_reservation(state["reservation_id"]),
        subtotal_amount=37560,
        refunded_amount=0,
        net_payable_amount=37560,
    )
    assert_reservation_state(
        workbench.read_reservation(second_reservation["id"]),
        booking_status="REBOOK_REQUIRED",
    )
    assert_reservation_money(
        workbench.read_reservation(second_reservation["id"]),
        subtotal_amount=33180,
        refunded_amount=33180,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        net_payable_amount=0,
    )


def test_welfare_check_increments_the_completed_count_on_its_segment(
    api, workbench, catalog, primary_leg, acceptance_agent_headers
):
    """Two appended checks raise the completed count on the slot they were performed
    during, and the nested collection filters by type.

    PRD §3.7: "The service stamps `recorded_at_utc` from the logical clock and
    `performed_by_user_id` from the acting `X-User-ID`, increments the slot's
    `completed_welfare_check_count`, and increments the slot's `version` by one."

    Design: Corner/endpoints/welfare_check_increments_the_completed_count_on_its_segment
    """
    leg = primary_leg()
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    segment = workbench.create_segment(animal["id"], leg["id"])

    first = workbench.append_welfare_check(
        segment["id"], check_type="VISUAL", outcome="NORMAL"
    )
    assert first["check_type"] == "VISUAL"
    second = workbench.append_welfare_check(
        segment["id"], check_type="FEED", notes="water topped up"
    )
    assert second["notes"] == "water topped up"

    assert_segment_state(
        workbench.read_segment(segment["id"]),
        completed_welfare_check_count=2,
        required_welfare_check_count=0,
    )

    rows, meta = validate_paginated(
        api.list_segment_welfare_checks(segment["id"], acceptance_agent_headers)
    )
    assert meta["total_count"] == 2
    assert sorted(ids_of(rows)) == sorted([first["id"], second["id"]])

    feed_rows, feed_meta = validate_paginated(
        api.list_segment_welfare_checks(
            segment["id"], acceptance_agent_headers, {"check_type": "FEED"}
        )
    )
    assert feed_meta["total_count"] == 1
    assert ids_of(feed_rows) == [second["id"]]
