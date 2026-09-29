"""Uniqueness, monotonicity and interval guards on programme configuration.

Each case pairs the refusal with a positive control, so the boundary between
"refused" and "accepted" is pinned rather than merely asserted.
"""

from test_helpers import (
    ApiErrorId,
    assert_station_bays,
    ids_of,
    kennel_allocation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_duplicate_station_iata_code_rejected(api, workbench, program_admin_headers):
    """A second station claiming an existing IATA code is refused and the stored
    row keeps its original country and bay pool.

    PRD §3.2: "A **station** is an airport in the programme, registered with an
    `iata_code` of exactly three uppercase letters and unique across all stations
    — a duplicate is `ERR_DUPLICATE_STATION_CODE`".

    Design: Corner/validations/duplicate_station_iata_code_rejected
    """
    first = workbench.create_station(
        iata_code="HKG", country_code="HK", kennel_bay_count=4
    )

    duplicate = api.create_station(
        {"iata_code": "HKG", "country_code": "CN", "kennel_bay_count": 9},
        program_admin_headers,
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_STATION_CODE, 409)

    rows, meta = validate_paginated(api.list_stations(program_admin_headers))
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first["id"]]

    stored = workbench.read_station(first["id"])
    assert stored["country_code"] == "HK"
    assert stored["kennel_bay_count"] == 4


def test_duplicate_active_breed_restriction_rejected(
    api, workbench, program_admin_headers
):
    """Breed names collide case-insensitively while a restriction is ACTIVE, and
    withdrawing the incumbent frees the name again.

    PRD §3.1: "a lowercased `breed_name` that duplicates an existing `ACTIVE`
    restriction of the same species — is refused with
    `ERR_DUPLICATE_BREED_RESTRICTION`."

    Design: Corner/validations/duplicate_active_breed_restriction_rejected
    """
    species = workbench.create_species()
    incumbent = workbench.create_breed_restriction(
        species["id"], breed_name="bulldog", restriction_type="SNUB_NOSED"
    )

    duplicate = api.create_breed_restriction(
        {
            "species_profile_id": species["id"],
            "breed_name": "BULLDOG",
            "restriction_type": "CARGO_ONLY",
        },
        program_admin_headers,
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_BREED_RESTRICTION, 409)

    assert workbench.read_species(species["id"])["breed_restriction_count"] == 1
    active_rows, active_meta = validate_paginated(
        api.list_species_breed_restrictions(
            species["id"], program_admin_headers, {"status": "ACTIVE"}
        )
    )
    assert active_meta["total_count"] == 1
    assert ids_of(active_rows) == [incumbent["id"]]

    workbench.set_breed_restriction_status(incumbent["id"], "WITHDRAWN")
    accepted = api.create_breed_restriction(
        {
            "species_profile_id": species["id"],
            "breed_name": "BULLDOG",
            "restriction_type": "CARGO_ONLY",
        },
        program_admin_headers,
    )
    replacement = validate_success(accepted, 201)
    assert replacement["restriction_type"] == "CARGO_ONLY"


def test_delay_moving_departure_earlier_rejected(api, workbench, primary_leg):
    """A delay must move the departure later; an earlier instant is refused and the
    leg keeps its schedule, its status and its version.

    PRD §3.3: "The leg must currently be `SCHEDULED`, the new departure must be
    strictly later than the leg's current `scheduled_departure_utc` (otherwise
    `ERR_SCHEDULE_NOT_MONOTONIC`) and the new arrival must be strictly after the
    new departure (otherwise `ERR_INVALID_TIME_RANGE`)."

    Design: Corner/validations/delay_moving_departure_earlier_rejected
    """
    leg = primary_leg()

    refused = api.delay_flight_leg(
        leg["id"],
        {
            "new_departure_utc": "2026-09-10T01:00:00Z",
            "new_arrival_utc": "2026-09-10T14:00:00Z",
        },
        workbench.admin(),
    )
    validate_error(refused, ApiErrorId.SCHEDULE_NOT_MONOTONIC, 422)

    unchanged = workbench.read_leg(leg["id"])
    assert unchanged["scheduled_departure_utc"] == "2026-09-10T02:00:00Z"
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["block_minutes"] == 780
    assert unchanged["version"] == leg["version"]

    delayed = validate_success(
        api.delay_flight_leg(
            leg["id"],
            {
                "new_departure_utc": "2026-09-10T04:00:00Z",
                "new_arrival_utc": "2026-09-10T18:00:00Z",
            },
            workbench.admin(),
        )
    )
    assert delayed["status"] == "DELAYED"
    assert delayed["scheduled_departure_utc"] == "2026-09-10T04:00:00Z"


def test_clock_set_to_earlier_instant_rejected(api, workbench):
    """The logical clock never runs backwards, and an instant equal to the current
    value is a no-op rather than an error.

    PRD §2.7: "a `to_iso8601` earlier than the current value is rejected with
    `ERR_CLOCK_NOT_MONOTONIC`, while an instant equal to the current value is
    accepted and leaves the clock unchanged."

    Design: Corner/validations/clock_set_to_earlier_instant_rejected
    """
    workbench.set_clock("2026-08-05T08:00:00Z")

    backwards = api.set_clock(
        {"to_iso8601": "2026-08-04T08:00:00Z"}, workbench.admin()
    )
    validate_error(backwards, ApiErrorId.CLOCK_NOT_MONOTONIC, 422)
    assert workbench.read_clock()["current_utc"] == "2026-08-05T08:00:00Z"

    idempotent = api.set_clock(
        {"to_iso8601": "2026-08-05T08:00:00Z"}, workbench.admin()
    )
    validate_success(idempotent)
    assert workbench.read_clock()["current_utc"] == "2026-08-05T08:00:00Z"


def test_kennel_allocation_with_end_before_start_rejected(
    api, workbench, screened_booking, acceptance_agent_headers
):
    """An occupancy window that ends before it starts, and one of zero length, are
    both refused, and the station's pool and version are untouched.

    PRD §3.7: "An `AcceptanceAgent` reserves bays by supplying the `station_id`
    providing them, the `animal_record_id` to be held, a `bay_count` of at least 1,
    an `occupancy_start_utc` and an `occupancy_end_utc` strictly after it (otherwise
    `ERR_INVALID_TIME_RANGE`)".

    Design: Corner/validations/kennel_allocation_with_end_before_start_rejected
    """
    state = screened_booking()
    station_id = state["catalog"]["hkg_id"]
    before = workbench.read_station(station_id)

    inverted = api.create_kennel_allocation(
        kennel_allocation_payload(
            station_id,
            state["animal_id"],
            before["version"],
            bay_count=1,
            occupancy_start_utc="2026-08-05T09:00:00Z",
            occupancy_end_utc="2026-08-05T06:00:00Z",
        ),
        acceptance_agent_headers,
    )
    validate_error(inverted, ApiErrorId.INVALID_TIME_RANGE, 422)

    zero_length = api.create_kennel_allocation(
        kennel_allocation_payload(
            station_id,
            state["animal_id"],
            before["version"],
            bay_count=1,
            occupancy_start_utc="2026-08-05T09:00:00Z",
            occupancy_end_utc="2026-08-05T09:00:00Z",
        ),
        acceptance_agent_headers,
    )
    validate_error(zero_length, ApiErrorId.INVALID_TIME_RANGE, 422)

    after = workbench.read_station(station_id)
    assert_station_bays(after, 0)
    assert after["version"] == before["version"]


def test_suspended_station_blocks_kennel_allocation_rejected(
    api, workbench, screened_booking, acceptance_agent_headers, program_admin_headers
):
    """A suspended station takes no holds at all, and the refusal names the
    suspension rather than the capacity rule below it.

    PRD §3.2: "While either the origin or the destination station of a leg is
    `SUSPENDED`, neither a routing slot on that leg nor a kennel hold at that
    station may be created, both being refused with `ERR_STATION_SUSPENDED`."

    Design: Corner/validations/suspended_station_blocks_kennel_allocation_rejected
    """
    state = screened_booking()
    station_id = state["catalog"]["hkg_id"]
    suspended = workbench.set_station_status(station_id, "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"

    refused = api.create_kennel_allocation(
        kennel_allocation_payload(
            station_id,
            state["animal_id"],
            suspended["version"],
            bay_count=2,
            occupancy_start_utc="2026-09-10T06:00:00Z",
            occupancy_end_utc="2026-09-10T09:00:00Z",
        ),
        acceptance_agent_headers,
    )
    validate_error(refused, ApiErrorId.STATION_SUSPENDED, 422)

    assert_station_bays(workbench.read_station(station_id), 0)
    _, meta = validate_paginated(
        api.list_kennel_allocations(program_admin_headers, {"station_id": station_id})
    )
    assert meta["total_count"] == 0
