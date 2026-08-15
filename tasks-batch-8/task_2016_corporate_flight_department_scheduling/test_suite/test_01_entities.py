"""Entity registration, retrieval, computed fields, system fields, FK integrity."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_aircraft,
    create_aircraft,
    create_aircraft_payload,
    create_passenger_profile_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    reset_clock,
    setup_bu_and_passenger,
    setup_submitted_trip,
    validate_error,
    validate_paginated,
    validate_success,
    add_leg,
    create_trip,
    make_executive_requester_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAircraftRegistration:
    def test_aircraft_creation_defaults(self, api):
        """PRD §3.1: "A newly registered aircraft starts with `status` set to
        `ACTIVE`; its `posture` and `posture_reason` are derived continuously per
        §2.7 rather than accepted as input."
        PRD §2.7: "Otherwise the posture is `AVAILABLE`."

        Design: Corner/entities/aircraft_creation_returns_201_and_defaults
        """
        reset_clock()
        resp = api.create_aircraft(
            create_aircraft_payload(tail_number="N2001CF", aircraft_type="TURBOPROP",
                                    passenger_capacity=8),
            MANAGER,
        )
        aircraft = validate_success(resp, 201)
        assert_aircraft(aircraft)
        assert aircraft["status"] == "ACTIVE", "new aircraft starts ACTIVE"
        assert aircraft["posture"] == "AVAILABLE", "no windows or lapsed docs -> AVAILABLE"
        assert aircraft["version"] == 1

    def test_aircraft_get_by_id_returns_matching_entity(self, api):
        """PRD §3.1: "A `FlightDeptManager` registers each aircraft by its
        `tail_number` — a registration string such as N123CF that is unique across
        the fleet — together with its `aircraft_type` ... its certified
        `passenger_capacity` of at least one seat, and its `home_base_icao`."

        Design: Corner/entities/aircraft_get_by_id_returns_matching_entity
        """
        aircraft = create_aircraft(tail_number="N2002CF", aircraft_type="LIGHT_JET",
                                   passenger_capacity=6)
        resp = api.get_aircraft(aircraft["id"], DISPATCHER)
        fetched = validate_success(resp, 200)
        assert_aircraft(fetched)
        assert fetched["id"] == aircraft["id"]
        assert fetched["tail_number"] == "N2002CF"
        assert fetched["passenger_capacity"] == 6

    def test_aircraft_get_nonexistent_returns_404(self, api):
        """PRD §2.6: "the system validates the existence of each identifier in
        sequential, left-to-right order and rejects the request with
        `ERR_NOT_FOUND` (HTTP 404) at the *first* path identifier that does not
        correspond to an existing resource."

        Design: Corner/entities/aircraft_get_nonexistent_returns_404
        """
        reset_clock()
        resp = api.get_aircraft(NON_EXISTENT_UUID, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_aircraft_invalid_enum_returns_400(self, api):
        """PRD §2.6: "A malformed body — wrong types, missing required fields,
        unparseable payloads — is rejected with `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "its `aircraft_type` (one of `LIGHT_JET`, `MIDSIZE_JET`,
        `HEAVY_JET`, or `TURBOPROP`)"

        Design: Corner/entities/aircraft_invalid_enum_returns_400
        """
        reset_clock()
        resp = api.create_aircraft(
            create_aircraft_payload(tail_number="N2003CF", aircraft_type="SPACESHIP"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_aircraft_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return. If not provided, it defaults to 10, with a minimum of 1 and
        maximum of 100."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/aircraft_list_pagination_envelope
        """
        reset_clock()
        for i in range(12):
            create_aircraft(tail_number=f"N21{i:02d}CF")
        resp = api.list_aircraft(DISPATCHER)
        data, meta = validate_paginated(resp)
        assert len(data) == 10, "default limit is 10"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        for row in data:
            assert_aircraft(row)


class TestSystemFields:
    def test_system_fields_id_created_at_version(self, api):
        """PRD §2.5: "**`id` (string):** A unique, system-generated identifier for
        the resource, formatted as a UUID with no type prefix."
        PRD §2.5: "**`created_at` (string):** An ISO 8601 timestamp in UTC with
        three fractional digits (e.g., `2026-08-01T12:00:00.123Z`) indicating when
        the resource was first created."
        PRD §2.5: "**`version` (integer):** A system-managed integer that
        increments with every modification to the resource"

        Design: Corner/entities/system_fields_id_created_at_updated_at_version
        """
        reset_clock()
        resp = api.create_aircraft(create_aircraft_payload(tail_number="N2005CF"), MANAGER)
        aircraft = validate_success(resp, 201)
        assert is_valid_uuid(aircraft["id"]), "server-minted UUID id"
        assert is_iso8601_timestamp(aircraft["created_at"])
        assert is_iso8601_timestamp(aircraft["updated_at"])
        assert aircraft["version"] == 1, "version starts at 1"


class TestComputedFields:
    def test_trip_submit_computes_max_priority_tier(self, api):
        """PRD §3.2: "Submission moves `approval_status` from `DRAFT` to
        `SUBMITTED` and recomputes `max_priority_tier` as the highest-priority
        tier present on the roster — `TIER_1` outranking `TIER_2` outranking
        `TIER_3`."

        Design: Corner/entities/trip_request_computed_max_priority_tier
        """
        reset_clock()
        bu, requester, trip, _legs = setup_submitted_trip(
            priority_tier="TIER_2", extra_passenger_tiers=("TIER_1",))
        resp = api.get_trip_request(trip["id"], MANAGER)
        data = validate_success(resp, 200)
        assert data["max_priority_tier"] == "TIER_1", (
            "highest tier on the roster wins, not the requester's own TIER_2"
        )

    def test_flight_leg_block_minutes_computed(self, api):
        """PRD §3.2: "The system derives `block_minutes` as the difference between
        arrival and departure in whole minutes, and each leg carries a
        `trip_request_id` back to its parent."

        Design: Corner/entities/flight_leg_block_minutes_computed
        """
        reset_clock()
        bu, pax = setup_bu_and_passenger()
        trip = create_trip(pax, bu["id"])
        headers = make_executive_requester_headers(pax["id"])
        resp = api.create_flight_leg(
            trip["id"],
            {
                "leg_sequence": 1,
                "origin_icao": "KTEB",
                "destination_icao": "KDCA",
                "scheduled_departure_utc": "2026-08-10T12:00:00Z",
                "scheduled_arrival_utc": "2026-08-10T14:37:00Z",
                "distance_statute_miles": 200,
            },
            headers,
        )
        leg = validate_success(resp, 201)
        assert leg["block_minutes"] == 157, "2h37m is 157 whole minutes"


class TestFkIntegrity:
    def test_passenger_home_bu_must_exist(self, api):
        """PRD §2.6: "any foreign key carried in a request body — `requester_id`,
        `charge_bu_id`, entries of `passenger_ids`, `aircraft_id`, the
        `pic_crew_id` and `sic_crew_id` pair, `trip_request_id`, or
        `flight_leg_id` — must resolve to an existing entity, or the request fails
        with `ERR_FK_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/fk_integrity_passenger_home_bu_must_exist
        """
        reset_clock()
        payload = create_passenger_profile_payload(home_bu_id=NON_EXISTENT_UUID)
        resp = api.create_passenger_profile(payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)
