"""Multi-level cascades: forecast embargo, fatal incident, leg delay, releases.

Every cascade in this file starts at one write and has to be observed several
levels away — on the leg, on the slot, on the station pool and finally in the
reservation's money — because each level is a separate stored row.
"""

from test_helpers import (
    ApiErrorId,
    THIRD_ACCEPTANCE_AGENT_ID,
    assert_charge_identity,
    assert_flight_leg_state,
    assert_incident_state,
    assert_reservation_money,
    assert_reservation_state,
    assert_segment_state,
    assert_station_bays,
    validate_error,
    validate_success,
)


def test_forecast_embargo_cascades_four_levels_to_net_payable(
    api, workbench, catalog, confirmed_booking
):
    """One forecast update moves the leg, the slot and the booked counter: the
    embargo branch takes the posture and the suppressed slot is released.

    PRD §3.3: "If the posture becomes `EMBARGOED`, the service immediately releases
    every routing slot on the leg that is still `RESERVED` and whose `routing_type` is
    contained in the governing rule's `applies_to_routings`".

    Design: Difficulty/transitive_cascade/forecast_embargo_cascades_four_levels_to_net_payable
    """
    state = confirmed_booking()
    rule = workbench.create_embargo_rule(
        catalog["hkg_id"], forecast_high_limit_c=29.5, forecast_low_limit_c=-5.0
    )

    embargoed = workbench.update_forecast(state["leg_id"], 30.0, 20.0)
    assert_flight_leg_state(
        embargoed,
        status="SCHEDULED",
        posture="EMBARGOED",
        governing_embargo_rule_id=rule["id"],
        booked_checked_count=0,
    )
    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="RELEASED",
        segment_fee_amount=33180,
    )


def test_forecast_embargo_cascade_drives_the_reservation_to_rebook_required(
    api, workbench, catalog, confirmed_booking
):
    """The fourth level of the same cascade is the money: the released slot's fee is
    refunded and the booking has nothing left to fly.

    PRD §3.3: "Each release decrements the corresponding booked counter, which
    re-derives the posture, and drives the owning reservation to `HOLD_PARTIAL` or
    `REBOOK_REQUIRED` with `refunded_amount` incremented by the released slot's
    `segment_fee_amount` and the reservation charge assembly re-run."

    Design: Difficulty/transitive_cascade/forecast_embargo_cascades_four_levels_to_net_payable
    """
    state = confirmed_booking()
    workbench.create_embargo_rule(
        catalog["hkg_id"], forecast_high_limit_c=29.5, forecast_low_limit_c=-5.0
    )
    workbench.update_forecast(state["leg_id"], 30.0, 20.0)

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_state(
        reservation, booking_status="REBOOK_REQUIRED", compliance_status="VERIFIED"
    )
    assert_reservation_money(
        reservation,
        subtotal_amount=33180,
        irops_fee_total=0,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        refunded_amount=33180,
        net_payable_amount=0,
    )
    assert_charge_identity(reservation)


def test_death_incident_cascades_through_segment_kennel_and_reservation(
    api, workbench, accepted_booking
):
    """Reporting a death takes the animal and its accepted slot down together, and the
    preliminary score already carries the in-transit adder.

    PRD §3.9: "Hop one sets the animal's `status` to `DECEASED`. Hop two moves every
    slot of the animal that is `RESERVED` to `RELEASED` and every slot that is
    `ACCEPTED` to `OFFLOADED`, each decrementing the booked counter for its routing on
    its owning leg and re-deriving that leg's posture."

    Design: Difficulty/transitive_cascade/death_incident_cascades_through_segment_kennel_and_reservation
    """
    state = accepted_booking(measured_weight_kg=27)
    workbench.create_kennel_allocation(
        state["catalog"]["hkg_id"], state["animal_id"], bay_count=2
    )

    incident = workbench.report_incident(
        state["animal_id"],
        as_user_id=THIRD_ACCEPTANCE_AGENT_ID,
        incident_type="DEATH",
        segment_assignment_id=state["segment_id"],
        discovered_at_utc="2026-08-01T12:00:00Z",
    )
    assert_incident_state(
        incident,
        status="REPORTED",
        preliminary_severity_score=95,
        adjudicated_severity_score=None,
        disclosure_required=True,
    )
    assert incident["reported_by_user_id"] == THIRD_ACCEPTANCE_AGENT_ID

    assert workbench.read_animal(state["animal_id"])["status"] == "DECEASED"
    assert_segment_state(
        workbench.read_segment(state["segment_id"]),
        status="OFFLOADED",
        segment_fee_amount=37560,
    )
    assert_flight_leg_state(
        workbench.read_leg(state["leg_id"]),
        status="SCHEDULED",
        posture="OPEN",
        booked_checked_count=0,
    )


def test_death_incident_releases_kennel_bays_and_interrupts_the_booking(
    api, workbench, accepted_booking
):
    """The third hop of the same cascade gives the bays back to the station and
    refunds the offloaded slot, interrupting the booking.

    PRD §3.9: "Hop three moves every kennel allocation for the animal whose `status` is
    `RESERVED` or `OCCUPIED` to `RELEASED`, decrementing that station's
    `reserved_bay_count` by the allocation's `bay_count`, sets the owning reservation's
    `booking_status` to `INTERRUPTED`, increments its `refunded_amount` by the
    `segment_fee_amount` of every slot released or offloaded in hop two, and re-runs the
    charge assembly."

    Design: Difficulty/transitive_cascade/death_incident_cascades_through_segment_kennel_and_reservation
    """
    state = accepted_booking(measured_weight_kg=27)
    hkg_id = state["catalog"]["hkg_id"]
    allocation = workbench.create_kennel_allocation(
        hkg_id, state["animal_id"], bay_count=2
    )
    assert_station_bays(workbench.read_station(hkg_id), 2)

    workbench.report_incident(
        state["animal_id"],
        as_user_id=THIRD_ACCEPTANCE_AGENT_ID,
        incident_type="DEATH",
        segment_assignment_id=state["segment_id"],
        discovered_at_utc="2026-08-01T12:00:00Z",
    )

    assert workbench.read_allocation(allocation["id"])["status"] == "RELEASED"
    assert_station_bays(workbench.read_station(hkg_id), 0)

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_state(reservation, booking_status="INTERRUPTED")
    assert_reservation_money(
        reservation,
        subtotal_amount=37560,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        refunded_amount=37560,
        net_payable_amount=0,
    )
    assert_charge_identity(reservation)


def test_leg_delay_cascades_through_connection_recompute_to_partial_hold(
    api, workbench, two_leg_confirmed_booking
):
    """Delaying the first leg shrinks the connection below the checked minimum, so the
    downstream slot on the *other* leg is what gets released.

    PRD §3.3: "In the second hop, every such slot whose recomputed `connection_minutes`
    has fallen below the connection minimum for its own `routing_type`, or has risen
    above the connection maximum, moves `RESERVED → RELEASED`, decrementing the booked
    counter for its routing on its own leg — which is generally a different leg from the
    delayed one — and re-deriving that leg's posture."

    Design: Difficulty/transitive_cascade/leg_delay_cascades_through_connection_recompute_to_partial_hold
    """
    state = two_leg_confirmed_booking()
    assert_segment_state(
        workbench.read_segment(state["segment2_id"]),
        status="RESERVED",
        connection_minutes=120,
        required_welfare_check_count=1,
    )

    delayed = workbench.delay_leg(
        state["leg1_id"], "2026-09-10T03:00:00Z", "2026-09-10T16:30:00Z"
    )
    assert_flight_leg_state(
        delayed, status="DELAYED", block_minutes=810, booked_checked_count=1
    )

    assert_segment_state(
        workbench.read_segment(state["segment2_id"]),
        status="RELEASED",
        segment_fee_amount=27650,
    )
    assert_segment_state(
        workbench.read_segment(state["segment1_id"]),
        status="RESERVED",
        segment_fee_amount=33180,
    )
    assert_flight_leg_state(
        workbench.read_leg(state["leg2_id"]), booked_checked_count=0, posture="OPEN"
    )


def test_leg_delay_cascade_holds_the_reservation_partially_and_refunds_one_slot(
    api, workbench, two_leg_confirmed_booking
):
    """Because one slot survives the recompute the booking is only partially held, and
    exactly the released slot's fee is refunded.

    PRD §3.3: "In the third hop, every reservation that owned a slot released in the
    second hop has its `booking_status` recomputed to `HOLD_PARTIAL` if it still retains
    at least one slot in `RESERVED` or `ACCEPTED` and to `REBOOK_REQUIRED` otherwise,
    has its `refunded_amount` incremented by each released slot's `segment_fee_amount`,
    and has the charge assembly re-run."

    Design: Difficulty/transitive_cascade/leg_delay_cascades_through_connection_recompute_to_partial_hold
    """
    state = two_leg_confirmed_booking()
    workbench.delay_leg(
        state["leg1_id"], "2026-09-10T03:00:00Z", "2026-09-10T16:30:00Z"
    )

    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_state(
        reservation, booking_status="HOLD_PARTIAL", compliance_status="VERIFIED"
    )
    assert_reservation_money(
        reservation,
        subtotal_amount=60830,
        irops_fee_total=0,
        loyalty_tier_pct=0,
        loyalty_discount_amount=0,
        refunded_amount=27650,
        net_payable_amount=33180,
    )
    assert_charge_identity(reservation)


def test_leg_routing_counter_returns_to_baseline_after_release(
    api, workbench, confirmed_booking
):
    """Releasing the only slot on the leg takes the booked counter back to the value it
    held before the slot existed, and the booking has nothing left to fly.

    PRD §3.5: "The slot's `status` becomes `RELEASED`, the owning leg's booked counter
    for its routing is decremented by one and the leg's posture is re-derived, the
    owning reservation's `refunded_amount` is incremented by the slot's
    `segment_fee_amount`, the reservation's `booking_status` is recomputed to
    `HOLD_PARTIAL` or `REBOOK_REQUIRED`, the charge assembly re-runs, and the leg's
    `version` increments by one."

    Design: Difficulty/compensating_invariant/leg_routing_counter_returns_to_baseline_after_release
    """
    state = confirmed_booking()
    assert_flight_leg_state(
        workbench.read_leg(state["leg_id"]), booked_checked_count=1, posture="OPEN"
    )

    released = validate_success(
        api.release_segment_assignment(
            state["segment_id"], workbench.agent(), {"reason": "passenger rebooking"}
        )
    )
    assert_segment_state(released, status="RELEASED", segment_fee_amount=33180)

    assert_flight_leg_state(
        workbench.read_leg(state["leg_id"]), booked_checked_count=0, posture="OPEN"
    )
    reservation = workbench.read_reservation(state["reservation_id"])
    assert_reservation_state(reservation, booking_status="REBOOK_REQUIRED")
    assert_reservation_money(
        reservation,
        subtotal_amount=33180,
        refunded_amount=33180,
        loyalty_discount_amount=0,
        net_payable_amount=0,
    )


def test_released_slot_stays_in_the_gross_subtotal_and_frees_the_posture(
    api, workbench, confirmed_booking
):
    """The compensation is an offset, not a deletion: the released slot's fee stays in
    the gross subtotal and the freed counter drops the leg out of `RESTRICTED`.

    PRD §3.8: "released and offloaded slots stay in this gross sum and are offset
    through `refunded_amount` rather than removed, which is what keeps
    `net_payable_amount` from going negative"

    Design: Difficulty/compensating_invariant/leg_routing_counter_returns_to_baseline_after_release
    """
    state = confirmed_booking(leg_overrides={"checked_animal_limit": 1})
    assert_flight_leg_state(
        workbench.read_leg(state["leg_id"]),
        booked_checked_count=1,
        posture="RESTRICTED",
    )

    workbench.release_segment(state["segment_id"])

    assert_flight_leg_state(
        workbench.read_leg(state["leg_id"]), booked_checked_count=0, posture="OPEN"
    )
    reservation = workbench.read_reservation(state["reservation_id"])
    assert reservation["subtotal_amount"] == 33180
    assert reservation["refunded_amount"] == 33180
    assert reservation["net_payable_amount"] == 0
    assert_charge_identity(reservation)


def test_station_suspension_outranks_routing_limit_rejected(
    api, workbench, catalog, primary_leg
):
    """A slot request that both lands on a suspended station and asks for a full
    routing answers with the suspension, which sits higher on the ladder.

    PRD §2.6: "29. Both the origin station's `status` and the destination station's
    `status` are `ACCEPTING` — otherwise `ERR_STATION_SUSPENDED` (422). Applies to two
    operations: `POST /segment-assignments` and `POST /kennel-allocations`."

    Design: Difficulty/priority_pair_validation_conflict/station_suspension_outranks_routing_limit_rejected
    """
    leg = primary_leg(checked_animal_limit=1)
    reservation = workbench.create_reservation()
    first_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    second_animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
        breed_name="Beagle",
        declared_weight_kg=12,
        height_at_shoulder_cm=30,
        length_nose_to_tail_cm=45,
        age_weeks=40,
    )
    workbench.create_segment(first_animal["id"], leg["id"])
    workbench.set_station_status(catalog["lax_id"], "SUSPENDED")

    refused = api.create_segment_assignment(
        {
            "animal_record_id": second_animal["id"],
            "flight_leg_id": leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 1,
            "expected_flight_leg_version": workbench.leg_version(leg["id"]),
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.STATION_SUSPENDED, 422)

    assert_flight_leg_state(
        workbench.read_leg(leg["id"]), booked_checked_count=1
    )


def test_routing_limit_answers_once_the_station_is_accepting_again(
    api, workbench, catalog, primary_leg
):
    """Resuming acceptance at the destination clears the higher rung, which lets the
    full routing answer as a conflict instead.

    PRD §2.6: "50. The leg's per-routing animal limit is not exceeded — otherwise
    `ERR_ROUTING_LIMIT_REACHED` (409). Applies to `POST /segment-assignments`."

    Design: Difficulty/priority_pair_validation_conflict/station_suspension_outranks_routing_limit_rejected
    """
    leg = primary_leg(checked_animal_limit=1)
    reservation = workbench.create_reservation()
    first_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    second_animal = workbench.create_animal(
        reservation["id"],
        catalog["species_id"],
        catalog["container_id"],
        animal_name="Taro",
        breed_name="Beagle",
        declared_weight_kg=12,
        height_at_shoulder_cm=30,
        length_nose_to_tail_cm=45,
        age_weeks=40,
    )
    workbench.create_segment(first_animal["id"], leg["id"])
    workbench.set_station_status(catalog["lax_id"], "SUSPENDED")
    workbench.set_station_status(catalog["lax_id"], "ACCEPTING")

    refused = api.create_segment_assignment(
        {
            "animal_record_id": second_animal["id"],
            "flight_leg_id": leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 1,
            "expected_flight_leg_version": workbench.leg_version(leg["id"]),
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.ROUTING_LIMIT_REACHED, 409)

    assert_flight_leg_state(
        workbench.read_leg(leg["id"]), booked_checked_count=1, posture="RESTRICTED"
    )
