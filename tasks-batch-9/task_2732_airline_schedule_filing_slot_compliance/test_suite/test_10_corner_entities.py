"""Entity-surface corners: creation defaults, computed fields, read-back
shape, pagination metadata, request-shape refusals and foreign-key existence.

Each class below pins one narrow promise about how a row is written, echoed or
refused, independently of the deeper cascades exercised elsewhere.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    api_client,
    assert_aircraft,
    assert_carrier,
    assert_flight_leg,
    assert_keys_absent,
    assert_schedule_version,
    assert_slot_utilization_record,
    assert_station,
    assert_timestamp_equals,
    assert_uuid,
    create_aircraft_payload,
    create_carrier,
    create_carrier_payload,
    create_flight_leg,
    create_flight_leg_payload,
    create_open_season,
    create_schedule_version,
    create_schedule_version_payload,
    create_season_payload,
    create_slot_holding,
    create_slot_holding_payload,
    create_station,
    create_station_payload,
    create_slot_utilization_record_payload,
    make_network_planner_headers,
    read_holding,
    read_leg,
    read_season,
    read_station,
    read_version,
    setup_international_rotation_base,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["slot_coordinator_headers"]
PLANNER = TEST_USERS["network_planner_headers"]


# ─── Creation defaults and server-minted identity ─────────────────────────

class TestCarrierCreationDefaults:
    """Four input fields in, a fully defaulted row out."""

    def test_a_new_carrier_is_active_with_no_series_and_version_one(self):
        """The two system-owned fields default and the audit block starts at 1.

        PRD §3.1: "Every carrier is created in `status` `ACTIVE` with
        `held_series_count` at 0."

        Design: Corner/entities/carrier_creation_returns_declared_defaults_and_version_one
        """
        response = api_client.create_carrier(
            create_carrier_payload(
                iata_code="HX", icao_code="HXA", country_code="DE", is_home_carrier=True
            ),
            ADMIN,
        )
        carrier = validate_success(response, expected_status=201)
        assert_carrier(carrier)

        assert carrier["iata_code"] == "HX"
        assert carrier["icao_code"] == "HXA"
        assert carrier["country_code"] == "DE"
        assert carrier["is_home_carrier"] is True
        assert carrier["status"] == "ACTIVE"
        assert carrier["held_series_count"] == 0
        assert carrier["version"] == 1
        assert_timestamp_equals(
            carrier["updated_at"], carrier["created_at"], "updated_at"
        )

    def test_client_supplied_identity_and_status_are_ignored(self):
        """A payload naming its own id, version and status is overruled.

        PRD §2.4: "Every resource in the system carries a server-minted `id`: a
        UUID string with no type prefix of any kind. Clients never supply an
        `id`."

        Design: Corner/entities/carrier_status_and_identity_are_server_minted_with_client_input_ignored
        """
        forged_id = "11111111-1111-4111-8111-111111111111"
        carrier = validate_success(
            api_client.create_carrier(
                create_carrier_payload(
                    iata_code="PT",
                    icao_code="PTA",
                    country_code="PT",
                    is_home_carrier=False,
                    id=forged_id,
                    version=77,
                    status="SUSPENDED",
                    held_series_count=9,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert_carrier(carrier)

        assert_uuid(carrier["id"])
        assert carrier["id"] != forged_id
        assert carrier["status"] == "ACTIVE"
        assert carrier["held_series_count"] == 0
        assert carrier["version"] == 1

    def test_the_server_minted_row_reads_back_the_same_way(self):
        """The forged values never reached storage either.

        PRD §2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row, again including
        derived-field-only mutations."

        Design: Corner/entities/carrier_status_and_identity_are_server_minted_with_client_input_ignored
        """
        forged_id = "11111111-1111-4111-8111-111111111111"
        carrier = validate_success(
            api_client.create_carrier(
                create_carrier_payload(
                    iata_code="PT",
                    icao_code="PTA",
                    country_code="PT",
                    is_home_carrier=False,
                    id=forged_id,
                    version=77,
                    status="SUSPENDED",
                ),
                ADMIN,
            ),
            expected_status=201,
        )

        validate_error(
            api_client.get_carrier(forged_id, ADMIN), ApiErrorId.ERR_CARRIER_NOT_FOUND
        )

        stored = validate_success(api_client.get_carrier(carrier["id"], ADMIN))
        assert stored["status"] == "ACTIVE"
        assert stored["version"] == 1
        assert stored["held_series_count"] == 0


class TestOmittedOptionalsTakeTheDeclaredDefaults:
    """Three entities, every optional input left out."""

    def test_a_station_created_bare_takes_its_connect_and_turn_defaults(self):
        """35, 60, 0, false and a pair of null curfew boundaries.

        PRD §3.1: "`min_connect_domestic_minutes` is the published minimum
        connect time when neither leg of a connection is international,
        defaulting to 35 minutes; `min_connect_international_minutes` is the
        minimum when either leg is international, defaulting to 60 minutes; both
        must be non-negative."

        Design: Corner/entities/omitted_optional_inputs_apply_the_declared_entity_defaults
        """
        station = validate_success(
            api_client.create_station(
                create_station_payload(
                    iata_code="MUC",
                    coordination_level="LEVEL_2_FACILITATED",
                    gate_count=3,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert_station(station)

        assert station["min_connect_domestic_minutes"] == 35
        assert station["min_connect_international_minutes"] == 60
        assert station["min_turn_override_minutes"] == 0
        assert station["maintenance_capable"] is False
        assert station["curfew_start_local_minutes"] is None
        assert station["curfew_end_local_minutes"] is None

    def test_a_tail_created_bare_is_in_service_and_unchecked(self):
        """The airworthiness default is the permissive one.

        PRD §3.3: "The tail's `status` describes its airworthiness and
        availability and defaults to `IN_SERVICE`; a tail may also be registered
        as `MAINTENANCE_GROUNDED` or `RETIRED`. On registration
        `assigned_leg_count` is 0 and `rotation_feasibility_status` is
        `UNCHECKED`."

        Design: Corner/entities/omitted_optional_inputs_apply_the_declared_entity_defaults
        """
        carrier = create_carrier()
        muc = create_station("MUC")
        planner = make_network_planner_headers(carrier["id"])

        aircraft = validate_success(
            api_client.create_aircraft(
                create_aircraft_payload(
                    carrier["id"], muc["id"], registration="D-AHXD"
                ),
                planner,
            ),
            expected_status=201,
        )
        assert_aircraft(aircraft)

        assert aircraft["status"] == "IN_SERVICE"
        assert aircraft["maintenance_check_required"] is False
        assert aircraft["assigned_leg_count"] == 0
        assert aircraft["maintenance_opportunity_minutes"] == 0
        assert aircraft["cumulative_ground_minutes"] == 0
        assert aircraft["rotation_feasibility_status"] == "UNCHECKED"

    def test_a_version_created_bare_carries_the_default_filing_budget(self):
        """100000 cents, a clean score and every counter still at 0.

        PRD §3.4: "The optional `filing_charge_budget_cents` sets the ceiling on
        cumulative filing charges the version may accrue; it defaults to 100000
        cents and must be non-negative."

        Design: Corner/entities/omitted_optional_inputs_apply_the_declared_entity_defaults
        """
        ref = setup_reference_data(("MUC",))

        version = validate_success(
            api_client.create_schedule_version(
                create_schedule_version_payload(
                    ref["carrier"]["id"], ref["season"]["id"], version_label="W26-D1"
                ),
                ref["planner"],
            ),
            expected_status=201,
        )
        assert_schedule_version(version)

        assert version["filing_charge_budget_cents"] == 100000
        assert version["filing_charge_accrued_cents"] == 0
        assert version["filing_status"] == "DRAFT"
        assert version["compliance_state"] == "CLEAN"
        assert version["leg_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["supersedes_version_id"] is None
        assert version["validated_by_user_id"] is None


# ─── Read-back and computed fields ────────────────────────────────────────

class TestStationReadBackEchoesTheOperatingConfiguration:
    """Every constraint the curfew and connect-time rules read lives here."""

    def _txl(self):
        return create_station(
            "TXL",
            gate_count=2,
            curfew_start_local_minutes=1380,
            curfew_end_local_minutes=330,
            min_connect_domestic_minutes=40,
            min_connect_international_minutes=75,
            min_turn_override_minutes=50,
            maintenance_capable=False,
        )

    def test_the_wrapping_curfew_pair_survives_the_round_trip(self):
        """A window that wraps past local midnight is stored as supplied.

        PRD §3.1: "`curfew_start_local_minutes` is the local minute at which the
        curfew opens and is treated as **inclusive**; `curfew_end_local_minutes`
        is the local minute at which it closes and is treated as **exclusive**."

        Design: Corner/entities/station_retrieval_returns_the_stored_operating_configuration
        """
        created = self._txl()

        station = read_station(created["id"], PLANNER)
        assert_station(station)
        assert station["iata_code"] == "TXL"
        assert station["coordination_level"] == "LEVEL_2_FACILITATED"
        assert station["utc_offset_minutes"] == 120
        assert station["gate_count"] == 2
        assert station["curfew_start_local_minutes"] == 1380
        assert station["curfew_end_local_minutes"] == 330

    def test_the_three_override_fields_survive_the_round_trip(self):
        """The connect minima and the turn floor are echoed, not defaulted.

        PRD §3.1: "`min_turn_override_minutes` is a station-imposed floor on
        aircraft ground time between two consecutive legs, defaulting to 0 and
        never negative"

        Design: Corner/entities/station_retrieval_returns_the_stored_operating_configuration
        """
        created = self._txl()

        station = read_station(created["id"], PLANNER)
        assert station["min_connect_domestic_minutes"] == 40
        assert station["min_connect_international_minutes"] == 75
        assert station["min_turn_override_minutes"] == 50
        assert station["maintenance_capable"] is False
        assert station["id"] == created["id"]
        assert station["version"] == 1


class TestFlightLegListingPagination:
    """Two legs, a page size of one, and the two metadata fields that matter."""

    def _two_legs(self):
        ref = setup_reference_data(("FRA", "MUC"))
        version = create_schedule_version(
            ref["carrier"]["id"], ref["season"]["id"], version_label="W26-P1"
        )
        legs = [
            create_flight_leg(
                ref["carrier"]["id"],
                version["id"],
                ref["stations"]["FRA"]["id"],
                ref["stations"]["MUC"]["id"],
                f"{date}T08:00:00.000Z",
                f"{date}T09:00:00.000Z",
                flight_number=number,
            )
            for number, date in (("HX101", "2026-11-02"), ("HX102", "2026-11-09"))
        ]
        ref["version"] = version
        ref["legs"] = legs
        return ref

    def _page(self, world, offset):
        return validate_paginated(
            api_client.list_flight_legs(
                world["planner"],
                params={
                    "schedule_version_id": world["version"]["id"],
                    "limit": 1,
                    "offset": offset,
                },
            )
        )

    def test_total_count_ignores_the_page_window(self):
        """One row on the page, two rows behind the filter.

        PRD §2.3: "Alongside the two echoed parameters, the `meta` object of a
        list response carries `total_count` - the number of rows matching the
        supplied filters before the page window is applied - and `has_more`, a
        boolean that is true exactly when rows matching the filters remain beyond
        the current window."

        Design: Corner/entities/flight_leg_listing_paginates_with_total_count_and_has_more
        """
        world = self._two_legs()

        rows, meta = self._page(world, 0)
        assert len(rows) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

    def test_the_last_window_reports_no_more_rows(self):
        """has_more is derived from the window, not from the page length.

        PRD §2.3: "Unless a subsection says otherwise, every list endpoint
        returns its rows sorted by `created_at` in ascending order, so that
        repeated paging over an unchanged collection is stable."

        Design: Corner/entities/flight_leg_listing_paginates_with_total_count_and_has_more
        """
        world = self._two_legs()

        first_rows, _ = self._page(world, 0)
        second_rows, meta = self._page(world, 1)

        assert len(second_rows) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["offset"] == 1

        assert first_rows[0]["id"] != second_rows[0]["id"]
        assert {first_rows[0]["id"], second_rows[0]["id"]} == {
            world["legs"][0]["id"],
            world["legs"][1]["id"],
        }


class TestFlightLegComputedFieldsIgnoreClientInput:
    """A leg payload that tries to dictate its own derived figures."""

    def _forged_leg_payload(self, world):
        return create_flight_leg_payload(
            world["version"]["id"],
            world["stations"]["MUC"]["id"],
            world["stations"]["LIS"]["id"],
            "2026-11-03T09:30:00.000Z",
            "2026-11-03T12:00:00.000Z",
            flight_number="HX440",
            fleet_type_code="A320",
            block_minutes=999,
            is_international=False,
            mct_shortfall_minutes=42,
        )

    def _world(self):
        return setup_international_rotation_base(
            version_label="W26-C1",
            station_overrides={"LIS": {"gate_count": 2, "maintenance_capable": False}},
        )

    def test_block_minutes_and_is_international_are_recomputed(self):
        """150 minutes and a DE-to-PT crossing, whatever the client claimed.

        PRD §3.4: "`block_minutes` is the whole number of minutes from `dep_utc`
        to `arr_utc`. `is_international` is true exactly when the `country_code`
        of the origin station differs from the `country_code` of the destination
        station."

        Design: Corner/entities/flight_leg_block_minutes_and_is_international_computed_with_client_input_ignored
        """
        world = self._world()

        leg = validate_success(
            api_client.create_flight_leg(
                self._forged_leg_payload(world), world["planner"]
            ),
            expected_status=201,
        )
        assert_flight_leg(leg)

        assert leg["block_minutes"] == 150
        assert leg["is_international"] is True

    def test_an_unconnected_leg_has_no_connect_time_and_no_shortfall(self):
        """The supplied shortfall of 42 is discarded along with the rest.

        PRD §3.4: "When `connects_from_leg_id` is null, `connect_minutes` is null
        and `mct_shortfall_minutes` is 0, and nothing further is checked."

        Design: Corner/entities/flight_leg_block_minutes_and_is_international_computed_with_client_input_ignored
        """
        world = self._world()

        leg = validate_success(
            api_client.create_flight_leg(
                self._forged_leg_payload(world), world["planner"]
            ),
            expected_status=201,
        )
        assert leg["connects_from_leg_id"] is None
        assert leg["connect_minutes"] is None
        assert leg["mct_shortfall_minutes"] == 0

        stored = read_leg(leg["id"], world["planner"])
        assert stored["block_minutes"] == 150
        assert stored["mct_shortfall_minutes"] == 0

    def test_the_rest_of_the_new_leg_is_the_declared_blank_slate(self):
        """No tail, no slots, no bookings and no obligations.

        PRD §3.4: "The leg is created in `status` `DRAFT` with
        `assigned_aircraft_id`, `departure_slot_holding_id` and
        `arrival_slot_holding_id` all null, all three booked-cabin counters at 0,
        `cancellation_reason` null, `open_obligation_count` at 0, and
        `block_minutes`, `is_international`, `connect_minutes` and
        `mct_shortfall_minutes` all computed."

        Design: Corner/entities/flight_leg_block_minutes_and_is_international_computed_with_client_input_ignored
        """
        world = self._world()

        leg = validate_success(
            api_client.create_flight_leg(
                self._forged_leg_payload(world), world["planner"]
            ),
            expected_status=201,
        )
        assert leg["status"] == "DRAFT"
        assert leg["assigned_aircraft_id"] is None
        assert leg["departure_slot_holding_id"] is None
        assert leg["arrival_slot_holding_id"] is None
        assert leg["cancellation_reason"] is None
        assert leg["open_obligation_count"] == 0
        assert leg["booked_first"] == 0
        assert leg["booked_business"] == 0
        assert leg["booked_economy"] == 0
        assert leg["version"] == 1

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 1
        # Neither MUC nor LIS is fully coordinated, so this leg requires no slot
        # at all and therefore never counts as unslotted.
        assert version["unslotted_leg_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)


# ─── Request-shape refusals, band 3 ───────────────────────────────────────

class TestRequestShapeRefusals:
    """A missing required field, an undeclared enum member and a repeated
    digit."""

    def test_a_season_without_its_return_deadline_is_malformed(self):
        """The deadline has no default, so omitting it is a shape error.

        PRD §2.9: "Every required field present; every enum field carrying a
        declared member; every timestamp parsing as ISO 8601 with a `Z` suffix;
        every integer field an integer inside its declared range; every monetary
        and count field non-negative; `days_of_week` a non-empty string of
        distinct digits drawn from 1 through 7; `limit` between 1 and 100 and
        `offset` non-negative. Otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/season_creation_without_slot_return_deadline_returns_invalid_request
        """
        payload = create_season_payload()
        del payload["slot_return_deadline_utc"]

        validate_error(
            api_client.create_season(payload, ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        rows, meta = validate_paginated(api_client.list_seasons(ADMIN))
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_fourth_coordination_level_is_not_a_declared_member(self):
        """The slot regime is keyed on this enum, so an unknown level is
        refused.

        PRD §2.9: "every enum field carrying a declared member; every timestamp
        parsing as ISO 8601 with a `Z` suffix; every integer field an integer
        inside its declared range; every monetary and count field non-negative;
        `days_of_week` a non-empty string of distinct digits drawn from 1 through
        7; `limit` between 1 and 100 and `offset` non-negative. Otherwise
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/station_coordination_level_outside_the_enum_returns_invalid_enum_request
        """
        validate_error(
            api_client.create_station(
                create_station_payload(
                    iata_code="ZZZ", coordination_level="LEVEL_4_SUPERCOORDINATED"
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        rows, meta = validate_paginated(api_client.list_stations(ADMIN))
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_repeated_weekday_digit_is_refused_rather_than_normalised(self):
        """A mask of 11 would count Monday twice and corrupt every percentage.

        PRD §2.9: "`days_of_week` a non-empty string of distinct digits drawn
        from 1 through 7; `limit` between 1 and 100 and `offset` non-negative.
        Otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/slot_holding_days_of_week_with_repeated_digit_returns_invalid_request
        """
        ref = setup_reference_data(("FRA",))

        validate_error(
            api_client.create_slot_holding(
                create_slot_holding_payload(
                    ref["stations"]["FRA"]["id"],
                    ref["season"]["id"],
                    ref["carrier"]["id"],
                    days_of_week="11",
                ),
                COORDINATOR,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        rows, meta = validate_paginated(
            api_client.list_slot_holdings(
                COORDINATOR, params={"station_id": ref["stations"]["FRA"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert read_season(ref["season"]["id"])["held_series_count"] == 0


# ─── Existence, band 4 ────────────────────────────────────────────────────

class TestExistenceRefusals:
    """Three unresolvable identifiers, each answered by its own error id."""

    def test_an_unknown_tail_identifier_is_a_not_found(self):
        """A well-formed UUID matching no row answers 404, not 200 or 500.

        PRD §2.9: "A carrier that does not resolve gives `ERR_CARRIER_NOT_FOUND`;
        a station, `ERR_STATION_NOT_FOUND`; a season, `ERR_SEASON_NOT_FOUND`; a
        tail, `ERR_AIRCRAFT_NOT_FOUND`"

        Design: Corner/entities/aircraft_get_with_unknown_id_returns_not_found
        """
        response = api_client.get_aircraft(MISSING_UUID, PLANNER)
        error = validate_error(
            response, ApiErrorId.ERR_AIRCRAFT_NOT_FOUND, expected_status=404
        )
        assert isinstance(error["message"], str)
        assert error["message"] != ""

        rows, meta = validate_paginated(api_client.list_aircraft(PLANNER))
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_leg_naming_an_unknown_version_is_a_not_found(self):
        """The body's foreign key is resolved before any business rule runs.

        PRD §2.9: "Path identifiers are resolved strictly left to right, and only
        then are foreign keys named in the body resolved."

        Design: Corner/entities/flight_leg_creation_with_unknown_schedule_version_returns_not_found
        """
        carrier = create_carrier()
        fra = create_station("FRA")
        muc = create_station("MUC")
        planner = make_network_planner_headers(carrier["id"])

        validate_error(
            api_client.create_flight_leg(
                create_flight_leg_payload(
                    "22222222-2222-4222-8222-222222222222",
                    fra["id"],
                    muc["id"],
                    "2026-11-02T08:00:00.000Z",
                    "2026-11-02T09:00:00.000Z",
                ),
                planner,
            ),
            ApiErrorId.ERR_SCHEDULE_VERSION_NOT_FOUND,
            expected_status=404,
        )

        rows, meta = validate_paginated(api_client.list_flight_legs(planner))
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_series_naming_an_unknown_carrier_is_a_not_found(self):
        """Two of the three foreign keys resolve; the carrier decides the
        answer.

        PRD §2.9: "A carrier that does not resolve gives `ERR_CARRIER_NOT_FOUND`;
        a station, `ERR_STATION_NOT_FOUND`; a season, `ERR_SEASON_NOT_FOUND`; a
        tail, `ERR_AIRCRAFT_NOT_FOUND`"

        Design: Corner/entities/slot_holding_creation_with_unknown_carrier_returns_carrier_not_found
        """
        fra = create_station("FRA")
        season = create_open_season()

        validate_error(
            api_client.create_slot_holding(
                create_slot_holding_payload(
                    fra["id"], season["id"], "33333333-3333-4333-8333-333333333333"
                ),
                COORDINATOR,
            ),
            ApiErrorId.ERR_CARRIER_NOT_FOUND,
            expected_status=404,
        )

        assert read_season(season["id"])["held_series_count"] == 0
        rows, meta = validate_paginated(api_client.list_slot_holdings(COORDINATOR))
        assert meta["total_count"] == 0
        assert rows == []


# ─── The one immutable resource ───────────────────────────────────────────

class TestSlotUtilizationRecordIsImmutable:
    """The append-only operating log: id and created_at, nothing else."""

    def _series(self):
        ref = setup_reference_data(("FRA",))
        ref["holding"] = create_slot_holding(
            ref["stations"]["FRA"]["id"],
            ref["season"]["id"],
            ref["carrier"]["id"],
            historic_precedence=False,
        )
        return ref

    def _file(self, ref):
        return api_client.create_slot_utilization_record(
            create_slot_utilization_record_payload(
                ref["holding"]["id"], "2026-11-02T00:00:00.000Z", "OPERATED"
            ),
            COORDINATOR,
        )

    def test_the_record_carries_no_version_and_no_updated_at(self):
        """Both audit keys are absent from the body rather than present and
        null.

        PRD §2.4: "It is immutable: there is no update endpoint for it, and it
        carries only `id` and `created_at`. It has neither an `updated_at` field
        nor a `version` field, and those two keys must be absent from its
        response body rather than present and null."

        Design: Corner/entities/slot_utilization_record_is_immutable_with_no_version_field
        """
        ref = self._series()

        record = validate_success(self._file(ref), expected_status=201)
        assert_slot_utilization_record(record)
        assert_keys_absent(record, "version", "updated_at")

        stored = validate_success(
            api_client.get_slot_utilization_record(record["id"], COORDINATOR)
        )
        assert_keys_absent(stored, "version", "updated_at")
        assert stored["id"] == record["id"]

    def test_filing_the_record_credits_the_series(self):
        """One operated day out of five planned is 20.00 percent.

        PRD §3.5: "On success the record's `credited` flag is set to true exactly
        when the `outcome` is one of the three crediting values, and
        `recorded_by_user_id` is stamped with the acting `X-User-ID`"

        Design: Corner/entities/slot_utilization_record_is_immutable_with_no_version_field
        """
        ref = self._series()

        record = validate_success(self._file(ref), expected_status=201)
        assert record["outcome"] == "OPERATED"
        assert record["credited"] is True
        assert record["recorded_by_user_id"] == "usr-coord-1"

        holding = read_holding(ref["holding"]["id"], COORDINATOR)
        assert holding["planned_operations"] == 5
        assert holding["credited_operations"] == 1
        assert holding["utilization_pct"] == pytest.approx(20.00, abs=0.01)
        # The as-filed variant is untouched: nothing is attached to the series.
        assert holding["attached_operations"] == 0
        assert holding["utilization_pct_as_filed"] == pytest.approx(0.00, abs=0.01)


# ─── Cross-reference integrity beyond mere existence ──────────────────────

class TestAttachSlotRequiresAnEndpointStation:
    """Both rows exist and share a carrier and a season; only the airport is
    wrong."""

    def _world(self):
        ref = setup_reference_data(("FRA", "DUS", "MUC"))
        ref["version"] = create_schedule_version(
            ref["carrier"]["id"], ref["season"]["id"], version_label="W26-F1"
        )
        ref["dus_holding"] = create_slot_holding(
            ref["stations"]["DUS"]["id"],
            ref["season"]["id"],
            ref["carrier"]["id"],
            historic_precedence=False,
        )
        ref["leg"] = create_flight_leg(
            ref["carrier"]["id"],
            ref["version"]["id"],
            ref["stations"]["FRA"]["id"],
            ref["stations"]["MUC"]["id"],
            "2026-11-02T08:00:00.000Z",
            "2026-11-02T09:00:00.000Z",
            flight_number="HX101",
        )
        return ref

    def test_a_series_at_a_third_airport_cannot_back_the_departure(self):
        """The holding is HELD, unencumbered and owned by the same carrier.

        PRD §3.5: "The series' `station_id` must equal the leg's
        `origin_station_id` when the movement type is `DEPARTURE` and its
        `dest_station_id` when the movement type is `ARRIVAL`, or the request
        fails with `ERR_SLOT_STATION_MISMATCH`."

        Design: Corner/entities/attach_slot_rejects_a_holding_whose_station_is_not_an_endpoint_of_the_leg
        """
        world = self._world()

        validate_error(
            api_client.attach_slot(
                world["leg"]["id"],
                {
                    "slot_holding_id": world["dus_holding"]["id"],
                    "movement_type": "DEPARTURE",
                },
                world["planner"],
            ),
            ApiErrorId.ERR_SLOT_STATION_MISMATCH,
            expected_status=422,
        )

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["status"] == "DRAFT"
        assert leg["departure_slot_holding_id"] is None

        holding = read_holding(world["dus_holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 0
        assert holding["utilization_pct_as_filed"] == pytest.approx(0.00, abs=0.01)
        assert holding["at_risk_of_loss"] is False

    def test_a_series_at_the_origin_backs_the_identical_movement(self):
        """Same leg, same movement type, same instant: only the airport
        changed.

        PRD §3.5: "A successful attach recomputes the series'
        `attached_operations`, `utilization_pct_as_filed` and `at_risk_of_loss`,
        and then the owning version's `unslotted_leg_count`, `at_risk_slot_count`,
        `schedule_compliance_score` and `compliance_state`."

        Design: Corner/entities/attach_slot_rejects_a_holding_whose_station_is_not_an_endpoint_of_the_leg
        """
        world = self._world()
        validate_error(
            api_client.attach_slot(
                world["leg"]["id"],
                {
                    "slot_holding_id": world["dus_holding"]["id"],
                    "movement_type": "DEPARTURE",
                },
                world["planner"],
            ),
            ApiErrorId.ERR_SLOT_STATION_MISMATCH,
        )

        fra_holding = create_slot_holding(
            world["stations"]["FRA"]["id"],
            world["season"]["id"],
            world["carrier"]["id"],
            historic_precedence=False,
        )
        leg = validate_success(
            api_client.attach_slot(
                world["leg"]["id"],
                {"slot_holding_id": fra_holding["id"], "movement_type": "DEPARTURE"},
                world["planner"],
            )
        )
        assert leg["departure_slot_holding_id"] == fra_holding["id"]
        # No tail has been assigned, so the leg stays exactly where it was.
        assert leg["status"] == "DRAFT"

        holding = read_holding(fra_holding["id"], COORDINATOR)
        assert holding["attached_operations"] == 1
        assert holding["utilization_pct_as_filed"] == pytest.approx(20.00, abs=0.01)
        assert holding["at_risk_of_loss"] is True
