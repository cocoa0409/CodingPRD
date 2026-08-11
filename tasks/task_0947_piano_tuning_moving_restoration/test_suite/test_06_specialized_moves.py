"""Specialized moves: the five price components and the buffered window rule."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_move_job,
    move_job_payload,
    move_job_transition,
    new_client,
    new_instrument,
    new_location,
    new_move_job,
    new_technician,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]
COORDINATOR = TEST_USERS["move_coordinator_headers"]


def _three_address_client():
    client = new_client(home_zone_code="ZONE_A")
    origin_two = new_location(
        client["id"], label="Origin 2F", address_key="north-quay-40",
        distance_miles_from_shop=12.0, stair_flights=2,
    )
    origin_three = new_location(
        client["id"], label="Origin 3F", address_key="north-quay-41",
        distance_miles_from_shop=12.0, stair_flights=3,
    )
    destination = new_location(
        client["id"], label="Destination", address_key="abbey-lane-9",
        distance_miles_from_shop=160.0, stair_flights=1,
    )
    instrument = new_instrument(
        client["id"], origin_two["id"], instrument_class="GRAND", usage_tier="STUDIO",
        make="Steinway", model="B",
    )
    return client, origin_two, origin_three, destination, instrument


def test_regional_move_is_priced_per_mile_at_the_upper_bound(api):
    """PRD 3.8: "Above 25.0 and up to 150.0 miles the band is `REGIONAL`, the variant is
    `PER_MILE`, and the charge is the mileage multiplied by 420 cents per mile and
    rounded half up — at exactly 150.0 miles that comes to 63000 cents."
    PRD 3.8: "When that total is at most 3, the charge is 9000 cents per flight, so
    three flights cost 27000 cents."
    PRD 3.8: "The **base component**, `base_cents`, is read straight off the
    instrument's class: 28000 cents for an `UPRIGHT`, 32000 for a `CONSOLE`, 52000 for a
    `BABY_GRAND`, 68000 for a `GRAND` and 145000 for a `CONCERT_GRAND`."
    PRD 3.8: "The **climate component**, `climate_cents`, is 38000 cents when
    `climate_controlled_transport` is true and 0 otherwise. `total_cents` is the plain
    sum of the five components."

    Design: Difficulty/dual_variant_calc/move_distance_per_mile_vs_long_haul_flat
    """
    _, origin_two, _, destination, instrument = _three_address_client()

    job = new_move_job(
        instrument["id"], origin_two["id"], destination["id"], 150.0,
        "2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z",
        crane_required=False, climate_controlled_transport=True,
    )

    assert_move_job(job)
    assert job["distance_band"] == "REGIONAL"
    assert job["distance_variant"] == "PER_MILE"
    assert job["distance_cents"] == 63000
    assert job["stair_flights_total"] == 3
    assert job["stair_cents"] == 27000
    assert job["base_cents"] == 68000
    assert job["climate_cents"] == 38000
    assert job["total_cents"] == 196000


def test_long_haul_move_over_four_flights_costs_less_than_the_regional_one(api):
    """PRD 3.8: "Above 150.0 miles the band is `LONG_HAUL`, the variant is
    `LONG_HAUL_FLAT`, and the charge is a flat 52000 cents — so a 151-mile move is
    cheaper than a 150-mile one, and this price too is deliberately not monotone."
    PRD 3.8: "When it reaches 4 or more, the charge collapses to a flat bundle of 25000
    cents regardless of how many flights there are — which means four flights cost
    **less** than three, and the stair price is deliberately not monotone in the flight
    count."

    Design: Difficulty/dual_variant_calc/move_distance_per_mile_vs_long_haul_flat
    """
    _, origin_two, origin_three, destination, instrument = _three_address_client()

    regional = new_move_job(
        instrument["id"], origin_two["id"], destination["id"], 150.0,
        "2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z",
        crane_required=False, climate_controlled_transport=True,
    )
    long_haul = new_move_job(
        instrument["id"], origin_three["id"], destination["id"], 151.0,
        "2026-05-20T09:00:00Z", "2026-05-20T11:00:00Z",
        crane_required=False, climate_controlled_transport=True,
    )

    assert long_haul["distance_band"] == "LONG_HAUL"
    assert long_haul["distance_variant"] == "LONG_HAUL_FLAT"
    assert long_haul["distance_cents"] == 52000
    assert long_haul["stair_flights_total"] == 4
    assert long_haul["stair_cents"] == 25000
    assert long_haul["total_cents"] == 183000
    assert long_haul["total_cents"] < regional["total_cents"], (
        "every input of the long-haul move is larger, yet it costs less"
    )


def test_move_window_widened_by_ninety_minutes_collides_on_a_touch(api):
    """PRD 3.8: "One booking rule guards the instrument: a new move's window, widened by
    90 minutes on **both** sides, must not intersect the *unwidened* window of any other
    move for the same instrument whose status is `DRAFT`, `SCHEDULED`, `DISPATCHED` or
    `IN_TRANSIT`. The comparison is a closed interval, so windows that merely touch
    after widening **do** collide — the opposite of the appointment-overlap rule. A
    collision is refused with `ERR_MOVE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/move_window_buffered_closed_interval_rejects_a_sixty_minute_gap
    """
    client = new_client(home_zone_code="ZONE_A")
    origin = new_location(client["id"], label="Origin", address_key="winward-70")
    destination = new_location(client["id"], label="Destination",
                               address_key="winward-71", distance_miles_from_shop=12.0)
    instrument = new_instrument(
        client["id"], origin["id"], instrument_class="GRAND", usage_tier="PERFORMANCE"
    )
    new_move_job(
        instrument["id"], origin["id"], destination["id"], 12.0,
        "2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z",
    )

    response = api.create_move_job(
        move_job_payload(
            instrument["id"], destination["id"], origin["id"], 12.0,
            "2026-05-10T12:30:00Z", "2026-05-10T14:30:00Z",
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_MOVE_WINDOW_CONFLICT.value)

    rows, _ = validate_paginated(
        api.list_move_jobs(MANAGER, params={"instrument_id": instrument["id"]})
    )
    assert len(rows) == 1, "the rejected window created nothing"


def test_move_window_one_minute_clear_of_the_buffer_is_accepted(api):
    """PRD 3.8: "One booking rule guards the instrument: a new move's window, widened by
    90 minutes on **both** sides, must not intersect the *unwidened* window of any other
    move for the same instrument whose status is `DRAFT`, `SCHEDULED`, `DISPATCHED` or
    `IN_TRANSIT`. The comparison is a closed interval, so windows that merely touch
    after widening **do** collide — the opposite of the appointment-overlap rule. A
    collision is refused with `ERR_MOVE_WINDOW_CONFLICT`."
    PRD 3.8: "At most 25.0 miles the `distance_band` is `LOCAL`, the `distance_variant`
    is `FLAT_LOCAL`, and the charge is a flat 6000 cents."

    Design: Difficulty/resource_temporal_overlap/move_window_buffered_closed_interval_rejects_a_sixty_minute_gap
    """
    client = new_client(home_zone_code="ZONE_A")
    origin = new_location(client["id"], label="Origin", address_key="winward-70")
    destination = new_location(client["id"], label="Destination",
                               address_key="winward-71", distance_miles_from_shop=12.0)
    instrument = new_instrument(
        client["id"], origin["id"], instrument_class="GRAND", usage_tier="PERFORMANCE"
    )
    new_move_job(
        instrument["id"], origin["id"], destination["id"], 12.0,
        "2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z",
    )

    second = validate_success(
        api.create_move_job(
            move_job_payload(
                instrument["id"], destination["id"], origin["id"], 12.0,
                "2026-05-10T12:31:00Z", "2026-05-10T14:31:00Z",
            ),
            COORDINATOR,
        ),
        201,
    )

    assert second["distance_band"] == "LOCAL"
    assert second["distance_variant"] == "FLAT_LOCAL"
    assert second["total_cents"] == 74000

    rows, _ = validate_paginated(
        api.list_move_jobs(MANAGER, params={"instrument_id": instrument["id"]})
    )
    assert len(rows) == 2


def test_concert_grand_over_two_flights_needs_a_crane(api):
    """PRD 3.8: "The **crane component**, `crane_cents`, is 185000 cents when
    `crane_required` is true and 0 otherwise. A `CONCERT_GRAND` whose
    `stair_flights_total` is at least 2 **must** set `crane_required` true; a job
    created without it is refused with `ERR_CRANE_REQUIRED`."
    PRD 3.8: "When that total is at most 3, the charge is 9000 cents per flight, so
    three flights cost 27000 cents."

    Design: Corner/validations/concert_grand_move_over_two_flights_without_a_crane_is_rejected
    """
    client = new_client(home_zone_code="ZONE_A")
    origin = new_location(client["id"], label="Upper Hall",
                          address_key="crane-origin", stair_flights=2)
    destination = new_location(client["id"], label="Ground Hall",
                               address_key="crane-dest", stair_flights=0,
                               distance_miles_from_shop=6.0)
    instrument = new_instrument(
        client["id"], origin["id"], instrument_class="CONCERT_GRAND",
        usage_tier="PERFORMANCE", make="Steinway", model="D",
    )

    response = api.create_move_job(
        move_job_payload(
            instrument["id"], origin["id"], destination["id"], 6.0,
            "2026-05-18T09:00:00Z", "2026-05-18T13:00:00Z", crane_required=False,
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_CRANE_REQUIRED.value)

    accepted = validate_success(
        api.create_move_job(
            move_job_payload(
                instrument["id"], origin["id"], destination["id"], 6.0,
                "2026-05-18T09:00:00Z", "2026-05-18T13:00:00Z", crane_required=True,
            ),
            COORDINATOR,
        ),
        201,
    )
    assert accepted["crane_cents"] == 185000
    assert accepted["stair_cents"] == 18000
    assert accepted["total_cents"] == 354000


def test_uncertified_crew_lead_cannot_schedule_a_crane_move(api):
    """PRD 3.8: "A `DRAFT` job moves to `SCHEDULED` once `move_technician_id` is set,
    and — when the instrument is a `CONCERT_GRAND` or `crane_required` is true — only
    when that crew lead's `move_certified` is true, failing which the answer is
    `ERR_MOVE_CREW_NOT_CERTIFIED`."
    PRD 2.8: "**Move crew certification.** A move of a `CONCERT_GRAND`, or any move with
    `crane_required` true, requires the crew lead's `move_certified` to be true.
    Otherwise `ERR_MOVE_CREW_NOT_CERTIFIED` (422). Applies to
    `POST /move-jobs/{id}/status-transitions`."

    Design: Corner/validations/uncertified_crew_cannot_schedule_a_concert_grand_move
    """
    client = new_client(home_zone_code="ZONE_A")
    origin = new_location(client["id"], label="Origin", address_key="crew-origin")
    destination = new_location(client["id"], label="Dest", address_key="crew-dest",
                               distance_miles_from_shop=6.0)
    instrument = new_instrument(
        client["id"], origin["id"], instrument_class="CONCERT_GRAND",
        usage_tier="PERFORMANCE", make="Fazioli", model="F308",
    )
    technician = new_technician(certification_level="JOURNEYMAN", move_certified=False)
    job = new_move_job(
        instrument["id"], origin["id"], destination["id"], 6.0,
        "2026-05-18T09:00:00Z", "2026-05-18T13:00:00Z",
        crane_required=True, move_technician_id=technician["id"],
    )
    assert job["total_cents"] == 336000, "the job itself is created without complaint"

    response = api.create_move_job_status_transition(
        job["id"], {"to_status": "SCHEDULED"}, COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_MOVE_CREW_NOT_CERTIFIED.value)

    assert validate_success(api.get_move_job(job["id"], MANAGER))["status"] == "DRAFT"


def test_dispatched_move_job_cannot_be_cancelled(api):
    """PRD 3.8: "A job in `DRAFT` or `SCHEDULED` may be cancelled. `DELIVERED` and
    `CANCELLED` are terminal, and every edge bumps the job's `version` by 1."
    PRD 2.8: "**Edge exists.** The requested transition must exist as an edge from the
    resource's current state in its own machine. Otherwise `ERR_INVALID_STATE` (409).
    Applies to every action operation that drives a state machine."

    Design: Corner/state_machines/move_job_cancel_from_dispatched_returns_invalid_state
    """
    client = new_client(home_zone_code="ZONE_A")
    origin = new_location(client["id"], label="Origin", address_key="mv-origin",
                          distance_miles_from_shop=3.0)
    destination = new_location(client["id"], label="Dest", address_key="mv-dest",
                               distance_miles_from_shop=6.0)
    instrument = new_instrument(client["id"], origin["id"])
    technician = new_technician(certification_level="JOURNEYMAN", move_certified=True)
    job = new_move_job(
        instrument["id"], origin["id"], destination["id"], 6.0,
        "2026-05-14T09:00:00Z", "2026-05-14T11:00:00Z",
        move_technician_id=technician["id"],
    )
    move_job_transition(job["id"], "SCHEDULED")
    move_job_transition(job["id"], "DISPATCHED")

    response = api.create_move_job_status_transition(
        job["id"], {"to_status": "CANCELLED", "reason": "customer called off"},
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_move_job(job["id"], MANAGER))
    assert after["status"] == "DISPATCHED"
    assert after["total_cents"] == 34000, "28000 UPRIGHT base plus the 6000 LOCAL flat"
