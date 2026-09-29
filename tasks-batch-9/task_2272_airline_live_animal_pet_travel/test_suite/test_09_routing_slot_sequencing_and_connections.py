"""Routing slots: mode agreement, contiguous sequencing, overlaps and connections.

Slot creation is the most heavily guarded write in the service, so most cases here
turn on which rung of the ladder answers when more than one rule is broken.
"""

from test_helpers import (
    ApiErrorId,
    assert_flight_leg_state,
    assert_segment_state,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_segment_routing_type_mismatched_with_reservation_rejected(
    api, workbench, catalog, primary_leg, program_admin_headers
):
    """A booking travels in one carriage mode throughout, so a cargo slot cannot be
    opened against a checked reservation.

    PRD §3.5: "The requested `routing_type` must equal the owning reservation's
    `routing_type`, since a booking travels in one mode throughout, and a mismatch is
    `ERR_ROUTING_MISMATCH`."

    Design: Corner/validations/segment_routing_type_mismatched_with_reservation_rejected
    """
    leg = primary_leg()
    reservation = workbench.create_reservation(routing_type="CHECKED")
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )

    refused = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": leg["id"],
            "routing_type": "CARGO",
            "sequence_index": 1,
            "expected_flight_leg_version": leg["version"],
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.ROUTING_MISMATCH, 422)

    after = workbench.read_leg(leg["id"])
    assert_flight_leg_state(after, booked_checked_count=0, booked_cargo_count=0)
    assert after["version"] == leg["version"]

    _, meta = validate_paginated(
        api.list_segment_assignments(
            program_admin_headers, {"animal_record_id": animal["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_segment_sequence_index_skipping_a_position_rejected(
    api, workbench, catalog, primary_leg, connecting_leg
):
    """The itinerary must be contiguous from position one, so neither a first slot at
    position two nor a third position after a first is accepted.

    PRD §3.5: "The `sequence_index` must be 1 for the animal's first slot and
    otherwise exactly one greater than the animal's current highest non-`RELEASED`
    `sequence_index`, and must not already be taken by a non-`RELEASED` slot; a
    skipped or duplicated position is `ERR_SEGMENT_SEQUENCE_INVALID`."

    Design: Corner/validations/segment_sequence_index_skipping_a_position_rejected
    """
    first_leg = primary_leg()
    second_leg = connecting_leg()
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )

    started_at_two = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": second_leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 2,
            "expected_flight_leg_version": second_leg["version"],
        },
        workbench.agent(),
    )
    validate_error(started_at_two, ApiErrorId.SEGMENT_SEQUENCE_INVALID, 422)

    workbench.create_segment(animal["id"], first_leg["id"], sequence_index=1)

    skipped_position = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": second_leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 3,
            "expected_flight_leg_version": workbench.leg_version(second_leg["id"]),
        },
        workbench.agent(),
    )
    validate_error(skipped_position, ApiErrorId.SEGMENT_SEQUENCE_INVALID, 422)

    contiguous = workbench.create_segment(
        animal["id"], second_leg["id"], sequence_index=2
    )
    assert_segment_state(contiguous, status="RESERVED", connection_minutes=120)
    assert contiguous["sequence_index"] == 2


def test_connection_above_maximum_window_rejected(api, workbench, catalog, primary_leg):
    """One minute past twelve hours is refused as a layover; twelve hours exactly is
    accepted and carries four welfare checks.

    PRD §3.5: "The gap must also not exceed twelve hours; a longer layover is refused
    with `ERR_CONNECTION_EXCEEDS_MAXIMUM`."

    Design: Corner/calculations/connection_above_maximum_window_rejected
    """
    first_leg = primary_leg()
    too_late = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN209",
        scheduled_departure_utc="2026-09-11T03:01:00Z",
        scheduled_arrival_utc="2026-09-11T08:00:00Z",
    )
    reservation = workbench.create_reservation(
        passenger_name="Chan", contact_email="chan@example.com", routing_type="CARGO"
    )
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.create_segment(
        animal["id"], first_leg["id"], routing_type="CARGO", sequence_index=1
    )

    refused = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": too_late["id"],
            "routing_type": "CARGO",
            "sequence_index": 2,
            "expected_flight_leg_version": too_late["version"],
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.CONNECTION_EXCEEDS_MAXIMUM, 422)
    assert_flight_leg_state(
        workbench.read_leg(too_late["id"]), booked_cargo_count=0
    )

    at_maximum = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN210",
        scheduled_departure_utc="2026-09-11T03:00:00Z",
        scheduled_arrival_utc="2026-09-11T08:00:00Z",
    )
    accepted = workbench.create_segment(
        animal["id"], at_maximum["id"], routing_type="CARGO", sequence_index=2
    )
    assert_segment_state(
        accepted,
        status="RESERVED",
        connection_minutes=720,
        required_welfare_check_count=4,
        completed_welfare_check_count=0,
    )


def test_cargo_connection_exactly_at_routing_minimum_accepted(
    api, workbench, catalog, primary_leg
):
    """Two hours exactly satisfies the cargo minimum, and the accepted slot carries
    the one welfare check the window demands.

    PRD §3.5: "That gap must be at least the connection minimum for the slot's own
    `routing_type` — one hour for `CABIN`, one and a half hours for `CHECKED`, and two
    hours for `CARGO`, since an animal travelling in the hold needs longer to be moved
    between aircraft — and a connection exactly equal to its minimum is accepted,
    while anything shorter is refused with `ERR_CONNECTION_BELOW_MINIMUM`."

    Design: Difficulty/boundary_precision_check/cargo_connection_exactly_at_routing_minimum_accepted
    """
    first_leg = primary_leg()
    second_leg = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN205",
        scheduled_departure_utc="2026-09-10T17:00:00Z",
        scheduled_arrival_utc="2026-09-10T22:00:00Z",
    )
    reservation = workbench.create_reservation(routing_type="CARGO")
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.create_segment(
        animal["id"], first_leg["id"], routing_type="CARGO", sequence_index=1
    )

    accepted = validate_success(
        api.create_segment_assignment(
            {
                "animal_record_id": animal["id"],
                "flight_leg_id": second_leg["id"],
                "routing_type": "CARGO",
                "sequence_index": 2,
                "expected_flight_leg_version": second_leg["version"],
            },
            workbench.agent(),
        ),
        201,
    )
    assert_segment_state(
        accepted,
        status="RESERVED",
        connection_minutes=120,
        required_welfare_check_count=1,
        completed_welfare_check_count=0,
    )
    assert_flight_leg_state(
        workbench.read_leg(second_leg["id"]), booked_cargo_count=1
    )


def test_cargo_connection_one_minute_below_routing_minimum_rejected(
    api, workbench, catalog, primary_leg, program_admin_headers
):
    """One minute short of the cargo minimum is refused, so the boundary is closed on
    the accepting side only.

    PRD §3.5: "and a connection exactly equal to its minimum is accepted, while
    anything shorter is refused with `ERR_CONNECTION_BELOW_MINIMUM`."

    Design: Difficulty/boundary_precision_check/cargo_connection_exactly_at_routing_minimum_accepted
    """
    first_leg = primary_leg()
    one_minute_short = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN206",
        scheduled_departure_utc="2026-09-10T16:59:00Z",
        scheduled_arrival_utc="2026-09-10T22:00:00Z",
    )
    reservation = workbench.create_reservation(routing_type="CARGO")
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    first_slot = workbench.create_segment(
        animal["id"], first_leg["id"], routing_type="CARGO", sequence_index=1
    )

    refused = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": one_minute_short["id"],
            "routing_type": "CARGO",
            "sequence_index": 2,
            "expected_flight_leg_version": one_minute_short["version"],
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.CONNECTION_BELOW_MINIMUM, 422)

    assert_flight_leg_state(
        workbench.read_leg(one_minute_short["id"]), booked_cargo_count=0
    )
    rows, meta = validate_paginated(
        api.list_segment_assignments(
            program_admin_headers, {"animal_record_id": animal["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first_slot["id"]]


def test_connection_minimum_outranks_routing_limit_rejected(
    api, workbench, catalog, primary_leg
):
    """A slot that both misses its connection minimum and asks for a full routing
    answers with the connection error, which sits higher on the ladder.

    PRD §2.6: "47. A connecting segment meets its routing connection minimum —
    otherwise `ERR_CONNECTION_BELOW_MINIMUM` (422). Applies to
    `POST /segment-assignments`."

    Design: Difficulty/priority_pair_validation_conflict/connection_minimum_outranks_routing_limit_rejected
    """
    first_leg = primary_leg()
    tight_leg = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN207",
        scheduled_departure_utc="2026-09-10T15:30:00Z",
        scheduled_arrival_utc="2026-09-10T20:30:00Z",
        checked_animal_limit=1,
    )
    reservation = workbench.create_reservation()
    connecting_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    other_animal = workbench.create_animal(
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
    workbench.create_segment(connecting_animal["id"], first_leg["id"], sequence_index=1)
    workbench.create_segment(other_animal["id"], tight_leg["id"], sequence_index=1)

    refused = api.create_segment_assignment(
        {
            "animal_record_id": connecting_animal["id"],
            "flight_leg_id": tight_leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 2,
            "expected_flight_leg_version": workbench.leg_version(tight_leg["id"]),
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.CONNECTION_BELOW_MINIMUM, 422)

    assert_flight_leg_state(
        workbench.read_leg(tight_leg["id"]), booked_checked_count=1
    )


def test_routing_limit_answers_once_the_connection_minimum_is_met(
    api, workbench, catalog, primary_leg
):
    """With the connection comfortably above its minimum the lower rung becomes
    reachable, and the full routing is refused as a conflict.

    PRD §2.6: "50. The leg's per-routing animal limit is not exceeded — otherwise
    `ERR_ROUTING_LIMIT_REACHED` (409). Applies to `POST /segment-assignments`."

    Design: Difficulty/priority_pair_validation_conflict/connection_minimum_outranks_routing_limit_rejected
    """
    first_leg = primary_leg()
    full_leg = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN208",
        scheduled_departure_utc="2026-09-10T17:00:00Z",
        scheduled_arrival_utc="2026-09-10T21:00:00Z",
        checked_animal_limit=1,
    )
    reservation = workbench.create_reservation()
    connecting_animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    other_animal = workbench.create_animal(
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
    workbench.create_segment(connecting_animal["id"], first_leg["id"], sequence_index=1)
    workbench.create_segment(other_animal["id"], full_leg["id"], sequence_index=1)

    refused = api.create_segment_assignment(
        {
            "animal_record_id": connecting_animal["id"],
            "flight_leg_id": full_leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 2,
            "expected_flight_leg_version": workbench.leg_version(full_leg["id"]),
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.ROUTING_LIMIT_REACHED, 409)

    assert_flight_leg_state(
        workbench.read_leg(full_leg["id"]), booked_checked_count=1
    )


def test_animal_itinerary_rejects_legs_that_only_touch_at_an_endpoint(
    api, workbench, catalog, primary_leg, program_admin_headers
):
    """A leg departing at the exact instant the previous one arrives already
    intersects it, because both intervals are closed.

    PRD §3.5: "The animal must not already hold another non-`RELEASED` slot whose
    leg's interval from `scheduled_departure_utc` to `scheduled_arrival_utc` intersects
    the requested leg's interval, where both intervals are **closed** so that merely
    touching endpoints already count as an intersection; an overlap is
    `ERR_ANIMAL_ITINERARY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/animal_itinerary_rejects_legs_that_only_touch_at_an_endpoint
    """
    first_leg = primary_leg()
    touching_leg = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN401",
        scheduled_departure_utc="2026-09-10T15:00:00Z",
        scheduled_arrival_utc="2026-09-10T19:00:00Z",
    )
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    first_slot = workbench.create_segment(
        animal["id"], first_leg["id"], sequence_index=1
    )

    refused = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": touching_leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 2,
            "expected_flight_leg_version": touching_leg["version"],
        },
        workbench.agent(),
    )
    validate_error(refused, ApiErrorId.ANIMAL_ITINERARY_OVERLAP, 409)

    assert_flight_leg_state(
        workbench.read_leg(touching_leg["id"]), booked_checked_count=0
    )
    rows, meta = validate_paginated(
        api.list_segment_assignments(
            program_admin_headers, {"animal_record_id": animal["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first_slot["id"]]


def test_itinerary_overlap_outranks_the_connection_minimum(
    api, workbench, catalog, primary_leg
):
    """Moving the departure one minute past the arrival stops the intervals touching,
    which lets the lower connection rung answer instead.

    PRD §2.6: "46. The animal has no other overlapping itinerary segment — otherwise
    `ERR_ANIMAL_ITINERARY_OVERLAP` (409). Applies to `POST /segment-assignments`."

    Design: Difficulty/resource_temporal_overlap/animal_itinerary_rejects_legs_that_only_touch_at_an_endpoint
    """
    first_leg = primary_leg()
    touching_leg = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN401",
        scheduled_departure_utc="2026-09-10T15:00:00Z",
        scheduled_arrival_utc="2026-09-10T19:00:00Z",
    )
    just_clear_leg = workbench.create_leg(
        catalog["lax_id"],
        catalog["jfk_id"],
        flight_number="AN402",
        scheduled_departure_utc="2026-09-10T15:01:00Z",
        scheduled_arrival_utc="2026-09-10T19:00:00Z",
    )
    reservation = workbench.create_reservation()
    animal = workbench.create_animal(
        reservation["id"], catalog["species_id"], catalog["container_id"]
    )
    workbench.create_segment(animal["id"], first_leg["id"], sequence_index=1)

    touching = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": touching_leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 2,
            "expected_flight_leg_version": touching_leg["version"],
        },
        workbench.agent(),
    )
    validate_error(touching, ApiErrorId.ANIMAL_ITINERARY_OVERLAP, 409)

    just_clear = api.create_segment_assignment(
        {
            "animal_record_id": animal["id"],
            "flight_leg_id": just_clear_leg["id"],
            "routing_type": "CHECKED",
            "sequence_index": 2,
            "expected_flight_leg_version": just_clear_leg["version"],
        },
        workbench.agent(),
    )
    validate_error(just_clear, ApiErrorId.CONNECTION_BELOW_MINIMUM, 422)
