"""Registering an arena, declaring its immutable house configurations, and the
shape of the booking and equipment rows those two records make possible."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    PROFILE_CONCERT,
    PROFILE_FAMILY,
    PROFILE_ICE,
    VENUE_DEFAULTS,
    assert_configuration_profile,
    assert_equipment_asset,
    assert_event_booking,
    assert_no_version_field,
    assert_venue,
    declare_profile,
    draft_booking,
    is_valid_uuid,
    place_hold,
    register_venue,
    set_clock,
    setup_arena,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]

RIVERTON = {
    "name": "Riverton Coliseum",
    "rigging_capacity_kg": 15_000,
    "dock_count": 3,
    "max_bowl_seats": 14_000,
    "crew_headcount_cap": 50,
}

UNKNOWN_BOOKING_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_VENUE_ID = "00000000-0000-4000-8000-000000000001"


def _three_hockey_dates():
    """One arena playing hockey on three consecutive September nights."""
    arena = setup_arena(profiles=("ICE",))
    arena["bookings"] = [
        draft_booking(
            arena["venue_id"], arena["profiles"]["ICE"]["id"], f"Hockey Sep {day}",
            f"2026-09-{day}T00:00:00Z", f"2026-09-{day}T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        for day in ("10", "11", "12")
    ]
    return arena


class TestArenaRegistration:
    def test_a_fresh_arena_reports_every_declared_field_with_its_counters_at_zero(
        self, api
    ):
        """PRD §3.1: "The registration supplies a `name` between 1 and 120 characters; a
        `rigging_capacity_kg` greater than zero, being the total combined suspended load the roof
        grid may carry across all time-overlapping committed events; a `dock_count` between 1 and
        8, which fixes the addressable truck docks; a `max_bowl_seats` greater than zero for the
        full-bowl capacity of the building; and a `crew_headcount_cap` between 1 and 200, the
        largest changeover crew the building may staff on a single shift."
        PRD §3.1: "A newly registered arena starts with `ice_deck_status` reading `NONE`,
        `rigging_committed_load_kg` at 0, `open_hold_count` at 0, `changeover_debt_minutes` at 0
        and `version` at 1."
        PRD §2.11: "The arena row carries four derived operational fields that are never written
        directly by a client."
        PRD §4: "Status codes follow one rule throughout: an operation that brings a new resource
        into existence answers with 201 Created, and every other successful operation — state
        transitions, reads, sweeps, maintenance actions and clock moves — answers with 200 OK."

        Design: Corner/entities/create_venue_returns_all_declared_fields_with_derived_counters_at_zero
        """
        set_clock(CLOCK_STARTUP_UTC)
        venue = validate_success(
            api.create_venue(dict(VENUE_DEFAULTS), DIRECTOR), 201
        )

        assert_venue(venue)
        assert venue["name"] == "Lakeside Arena"
        assert float(venue["rigging_capacity_kg"]) == pytest.approx(20_000, abs=0.005)
        assert venue["dock_count"] == 4
        assert venue["max_bowl_seats"] == 18_000
        assert venue["crew_headcount_cap"] == 60
        assert venue["ice_deck_status"] == "NONE"
        assert float(venue["rigging_committed_load_kg"]) == pytest.approx(
            0.00, abs=0.005
        )
        assert venue["open_hold_count"] == 0
        assert venue["changeover_debt_minutes"] == 0
        assert venue["version"] == 1

    def test_reading_the_arena_back_echoes_the_stored_row_and_bumps_no_version(
        self, api
    ):
        """PRD §3.1: "`min_turnaround_buffer_minutes` is the mandatory idle buffer inserted after
        an outgoing event's end before a changeover window may open; it accepts 0 through 240 and
        defaults to three quarters of an hour."
        PRD §4: "Read one arena including its four derived operational fields and its concurrency
        version."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases
        by exactly 1 on every accepted mutation of that row."

        Design: Corner/entities/get_venue_returns_the_stored_row_unchanged
        """
        set_clock(CLOCK_STARTUP_UTC)
        payload = {
            key: value
            for key, value in VENUE_DEFAULTS.items()
            if key != "min_turnaround_buffer_minutes"
        }
        created = validate_success(api.create_venue(payload, DIRECTOR), 201)

        read_back = validate_success(api.get_venue(created["id"], SUPERVISOR), 200)

        assert read_back["name"] == "Lakeside Arena"
        assert read_back["min_turnaround_buffer_minutes"] == 45, (
            "the omitted buffer defaults to three quarters of an hour"
        )
        assert read_back["dock_buffer_minutes"] == 30
        assert read_back["overnight_shift_start_local_hour"] == 22
        assert read_back["dock_count"] == 4
        assert read_back["crew_headcount_cap"] == 60
        assert read_back["version"] == 1, "a read is not a mutation"
        assert read_back["id"] == created["id"]

    def test_the_server_mints_its_own_id_timestamp_and_version(self, api):
        """PRD §2.4: "Every resource the API persists is addressed by an `id` that the server
        mints as a UUID."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases
        by exactly 1 on every accepted mutation of that row."

        Design: Corner/entities/venue_system_fields_are_server_generated_and_client_values_ignored_input_ignored
        """
        set_clock(CLOCK_STARTUP_UTC)
        payload = dict(VENUE_DEFAULTS)
        payload.update(
            {
                "id": "client-supplied-id",
                "created_at": "2020-01-01T00:00:00Z",
                "version": 99,
            }
        )

        venue = validate_success(api.create_venue(payload, DIRECTOR), 201)

        assert venue["id"] != "client-supplied-id"
        assert is_valid_uuid(venue["id"])
        assert venue["version"] == 1, "the submitted 99 is ignored"


class TestBookingListingAndLookup:
    def test_a_two_row_page_reports_the_full_count_and_more_to_come(self, api):
        """PRD §2.3: "`limit` controls page size: its default is 10, its minimum accepted value
        is 1, and its maximum accepted value is 100."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`
        (the number of rows matching the filters before pagination is applied) and `has_more`
        (true when rows remain beyond the current page)."
        PRD §2.3: "Results are ordered by `created_at` ascending unless the endpoint's own
        description in §3 pins a different order."

        Design: Corner/entities/list_event_bookings_paginates_with_total_count_and_has_more
        """
        arena = _three_hockey_dates()

        first_rows, first_meta = validate_paginated(
            api.list_event_bookings(
                MANAGER, {"venue_id": arena["venue_id"], "limit": 2, "offset": 0}
            )
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_rows, second_meta = validate_paginated(
            api.list_event_bookings(
                MANAGER, {"venue_id": arena["venue_id"], "limit": 2, "offset": 2}
            )
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        seen = [row["id"] for row in first_rows + second_rows]
        assert len(set(seen)) == 3, "the two pages must not repeat a row"
        assert set(seen) == {booking["id"] for booking in arena["bookings"]}

    def test_an_unknown_booking_id_is_a_not_found_error_and_not_an_empty_envelope(
        self, api
    ):
        """PRD §2.9: "The unresolved-identifier vocabulary is specific: `ERR_VENUE_NOT_FOUND` for
        an arena, `ERR_PROFILE_NOT_FOUND` for a `config_profile_id`, `ERR_TENANT_NOT_FOUND` for a
        `tenant_id` or a `challenger_tenant_id`, `ERR_BOOKING_NOT_FOUND` for any booking
        reference in a path or body, `ERR_CHALLENGE_NOT_FOUND` for a challenge in a path,
        `ERR_CHANGEOVER_ORDER_NOT_FOUND` for a turnaround in a path or body,
        `ERR_ICE_SHEET_NOT_FOUND` for an ice sheet in a path, `ERR_DOCK_RESERVATION_NOT_FOUND`
        for a dock reservation in a path, `ERR_LABOR_CALL_NOT_FOUND` for a labor call in a path,
        and `ERR_EQUIPMENT_NOT_FOUND` for either an equipment pool or an equipment issue in a
        path or body."
        PRD §2.9: "All ten carry HTTP 404."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/entities/get_event_booking_with_unknown_id_returns_not_found
        """
        setup_arena(profiles=("ICE",))

        response = api.get_event_booking(UNKNOWN_BOOKING_ID, MANAGER)

        validate_error(response, ApiErrorId.ERR_BOOKING_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"


class TestBookingDraftShapeAndDefaults:
    def test_omitting_the_house_configuration_reference_is_a_malformed_request(
        self, api
    ):
        """PRD §2.10: "Every required input field present, every enum value a member of its
        declared set, every numeric field inside its declared bounds, `event_end_utc` strictly
        after `event_start_utc`, `window_end_utc` strictly after `window_start_utc`,
        `call_end_utc` strictly after `call_start_utc`, `expected_attendance` no greater than the
        configuration profile's `nominal_seats`, `promoter_name` present whenever `tenant_id` is
        absent, `damaged_units` no greater than the issue's `units_issued`, and
        `sheet_thickness_mm` between 18 and 45 inclusive."
        PRD §2.10: "Any breach is `ERR_INVALID_REQUEST`."
        PRD §3.3: "The payload names the arena as `venue_id` and the house configuration as
        `config_profile_id`, gives the show a `title` of 1 to 160 characters, and pins the show's
        own footprint on the calendar with `event_start_utc` and `event_end_utc` — the
        doors-to-curtain start and the end instant, both ISO 8601 UTC, with the end strictly
        after the start."

        Design: Corner/entities/create_event_booking_missing_required_config_profile_id_is_rejected
        """
        arena = setup_arena(profiles=("ICE",))

        response = api.create_event_booking(
            {
                "venue_id": arena["venue_id"],
                "title": "Hockey Sep 10",
                "promoter_name": "Lakeside Hockey Club",
                "event_start_utc": "2026-09-10T00:00:00Z",
                "event_end_utc": "2026-09-10T03:00:00Z",
                "expected_attendance": 15_000,
                "rigging_load_kg": 3_000,
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _rows, meta = validate_paginated(
            api.list_event_bookings(MANAGER, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 0, "a rejected draft leaves no row behind"

    def test_a_show_that_hangs_nothing_from_the_grid_stores_a_zero_load(self, api):
        """PRD §3.3: "`rigging_load_kg` declares the suspended load the show hangs from the roof
        grid; it must be at least zero and defaults to zero when omitted."
        PRD §3.3: "A fresh draft has `status` reading `DRAFT`; `hold_tier`, `hold_placed_at`,
        `hold_expires_at`, `release_reason` and `displaced_by_booking_id` all unset; and
        `displacement_penalty_cents` at 0."

        Design: Corner/entities/create_event_booking_omitting_rigging_load_kg_applies_the_zero_default
        """
        arena = setup_arena(profiles=("ICE",))

        booking = validate_success(
            api.create_event_booking(
                {
                    "venue_id": arena["venue_id"],
                    "config_profile_id": arena["profiles"]["ICE"]["id"],
                    "title": "Rigging-free skate",
                    "promoter_name": "Community Skate",
                    "event_start_utc": "2026-09-10T00:00:00Z",
                    "event_end_utc": "2026-09-10T03:00:00Z",
                    "expected_attendance": 5_000,
                },
                MANAGER,
            ),
            201,
        )

        assert_event_booking(booking)
        assert float(booking["rigging_load_kg"]) == pytest.approx(0.0, abs=0.005)
        assert booking["status"] == "DRAFT"
        assert booking["displacement_penalty_cents"] == 0
        assert booking["hold_tier"] is None
        assert booking["hold_placed_at"] is None
        assert booking["hold_expires_at"] is None
        assert booking["displaced_by_booking_id"] is None


class TestEquipmentPoolDerivedFields:
    def test_submitted_availability_and_service_flags_are_overwritten_by_the_derivation(
        self, api
    ):
        """PRD §3.9: "A new pool has `units_available` equal to `units_total`,
        `units_out_of_service` at 0, `cycles_since_service` at 0, `service_due` false and
        `status` reading `IN_SERVICE`, the only alternative being `OUT_OF_SERVICE`."
        PRD §3.9: "Availability is always derived, never written directly: `units_available` is
        `units_total` less `units_out_of_service` less the sum of `units_issued` across every
        equipment issue on that pool whose `status` is `ISSUED`."
        PRD §3.9: "`service_due` is likewise derived, and it is evaluated inclusively: the flag
        is true as soon as `cycles_since_service` reaches `service_interval_cycles`, so the
        interval-th cycle already flags the pool rather than the one after it."

        Design: Corner/entities/equipment_asset_units_available_is_computed_and_extra_client_input_ignored
        """
        arena = setup_arena(profiles=())

        asset = validate_success(
            api.create_equipment_asset(
                arena["venue_id"],
                {
                    "asset_class": "FLOOR_PANEL_SET",
                    "units_total": 10,
                    "service_interval_cycles": 12,
                    "units_available": 3,
                    "service_due": True,
                },
                DIRECTOR,
            ),
            201,
        )

        assert_equipment_asset(asset)
        assert asset["units_available"] == 10, "the submitted 3 is ignored"
        assert asset["service_due"] is False, "the submitted true is ignored"
        assert asset["units_out_of_service"] == 0
        assert asset["cycles_since_service"] == 0
        assert asset["status"] == "IN_SERVICE"
        assert asset["units_total"] == 10


class TestHouseConfigurationDeclaration:
    def test_a_bowl_treatment_outside_the_declared_set_and_a_zero_length_show_are_both_malformed(
        self, api
    ):
        """PRD §3.1: "`seating_mode` describes the bowl treatment and is one of `FULL_BOWL`,
        `RETRACTABLE_IN` or `CURTAINED_HALF`."
        PRD §2.10: "Every required input field present, every enum value a member of its declared
        set, every numeric field inside its declared bounds, `event_end_utc` strictly after
        `event_start_utc`, `window_end_utc` strictly after `window_start_utc`, `call_end_utc`
        strictly after `call_start_utc`, `expected_attendance` no greater than the configuration
        profile's `nominal_seats`, `promoter_name` present whenever `tenant_id` is absent,
        `damaged_units` no greater than the issue's `units_issued`, and `sheet_thickness_mm`
        between 18 and 45 inclusive."
        PRD §2.10: "Any breach is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_configuration_profile_with_an_invalid_seating_mode_enum_is_rejected
        """
        arena = setup_arena(profiles=("ICE",))

        bad_enum = dict(PROFILE_FAMILY)
        bad_enum["seating_mode"] = "HALF_HOUSE"
        validate_error(
            api.create_configuration_profile(arena["venue_id"], bad_enum, DIRECTOR),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        zero_length = api.create_event_booking(
            {
                "venue_id": arena["venue_id"],
                "config_profile_id": arena["profiles"]["ICE"]["id"],
                "title": "Zero-length event",
                "promoter_name": "Lakeside Hockey Club",
                "event_start_utc": "2026-09-10T00:00:00Z",
                "event_end_utc": "2026-09-10T00:00:00Z",
                "expected_attendance": 15_000,
                "rigging_load_kg": 3_000,
            },
            MANAGER,
        )
        validate_error(
            zero_length, ApiErrorId.ERR_INVALID_REQUEST.value, 400
        )

        _rows, meta = validate_paginated(
            api.list_configuration_profiles(arena["venue_id"], DIRECTOR)
        )
        assert meta["total_count"] == 1, "only the ice configuration was ever accepted"

    def test_a_declared_configuration_is_read_only_and_carries_no_concurrency_version(
        self, api
    ):
        """PRD §3.1: "A configuration profile is immutable once declared; it is only ever created
        and read."
        PRD §2.4: "House configuration profiles are the one exception."
        PRD §2.4: "A configuration profile is immutable once declared, so it carries only `id` and
        `created_at`."
        PRD §2.4: "It has no `updated_at` field and no `version` field at all — neither key
        appears in its response payload."
        PRD §3.1: "The arena's profile list can be narrowed by `code`."

        Design: Corner/entities/configuration_profile_is_immutable_with_no_update_endpoint_and_no_version_field
        """
        arena = setup_arena(profiles=("ICE", "CONCERT"))

        rows, meta = validate_paginated(
            api.list_configuration_profiles(arena["venue_id"], SUPERVISOR)
        )
        assert meta["total_count"] == 2

        for row in rows:
            assert_configuration_profile(row)
            assert_no_version_field(row)

        by_code = {row["code"]: row for row in rows}
        ice = by_code["ICE_HOCKEY"]
        assert ice["base_changeover_minutes"] == PROFILE_ICE[
            "base_changeover_minutes"
        ] == 240
        assert float(ice["dehumidification_required_lph"]) == pytest.approx(
            120, abs=0.005
        )
        concert = by_code["CONCERT_END_STAGE"]
        assert concert["floor_protection_panels_required"] == PROFILE_CONCERT[
            "floor_protection_panels_required"
        ] == 120
        assert concert["seating_mode"] == "CURTAINED_HALF"

    def test_declaring_a_configuration_under_an_unknown_building_is_a_not_found(
        self, api
    ):
        """PRD §3.1: "Each profile belongs to the arena named in its path and records that arena's
        `venue_id`."
        PRD §2.9: "Path parameters are validated strictly left to right."
        PRD §2.9: "When a nested path names an arena that does not exist, the response is
        `ERR_VENUE_NOT_FOUND` regardless of what else the request gets wrong."
        PRD §2.9: "All ten carry HTTP 404."

        Design: Corner/entities/create_configuration_profile_under_an_unknown_venue_returns_not_found
        """
        arena = setup_arena(profiles=())

        response = api.create_configuration_profile(
            UNKNOWN_VENUE_ID, dict(PROFILE_ICE), DIRECTOR
        )
        validate_error(response, ApiErrorId.ERR_VENUE_NOT_FOUND.value, 404)

        _rows, meta = validate_paginated(
            api.list_configuration_profiles(arena["venue_id"], DIRECTOR)
        )
        assert meta["total_count"] == 0, "no orphan profile was created anywhere"


class TestArenaScopingAcrossTwoBuildings:
    def test_a_draft_cannot_borrow_the_other_buildings_house_configuration(self, api):
        """PRD §3.3: "Both the named configuration profile and, when present, the named anchor
        tenant must belong to the same arena as the booking, or the draft is rejected with
        `ERR_VENUE_SCOPE_MISMATCH`."
        PRD §2.9: "The resource graph is flat: every entity is its own top-level collection,
        joined by explicit references carried in payloads and query filters."
        PRD §3.1: "Each profile belongs to the arena named in its path and records that arena's
        `venue_id`."

        Design: Corner/entities/event_booking_rejects_a_configuration_profile_belonging_to_another_venue
        """
        set_clock(CLOCK_STARTUP_UTC)
        lakeside = register_venue()
        riverton = register_venue(**RIVERTON)
        riverton_ice = declare_profile(riverton["id"], "ICE")

        response = api.create_event_booking(
            {
                "venue_id": lakeside["id"],
                "config_profile_id": riverton_ice["id"],
                "title": "Cross-venue booking",
                "promoter_name": "Lakeside Hockey Club",
                "event_start_utc": "2026-09-10T00:00:00Z",
                "event_end_utc": "2026-09-10T03:00:00Z",
                "expected_attendance": 12_000,
                "rigging_load_kg": 3_000,
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_VENUE_SCOPE_MISMATCH.value, 409)

        _rows, meta = validate_paginated(
            api.list_event_bookings(MANAGER, {"venue_id": lakeside["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_turnaround_cannot_span_two_buildings(self, api):
        """PRD §3.7: "The order's own `venue_id` is copied from the incoming booking's arena
        rather than supplied by the caller."
        PRD §3.7: "Last, both bookings must share the same arena, otherwise
        `ERR_VENUE_SCOPE_MISMATCH`."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases
        by exactly 1 on every accepted mutation of that row."

        Design: Corner/entities/changeover_order_across_two_venues_is_rejected_for_venue_scope
        """
        set_clock(CLOCK_STARTUP_UTC)
        lakeside = register_venue()
        lakeside_ice = declare_profile(lakeside["id"], "ICE")
        riverton = register_venue(**RIVERTON)
        riverton_concert = declare_profile(riverton["id"], "CONCERT")

        hockey = draft_booking(
            lakeside["id"], lakeside_ice["id"], "Hockey Sep 10",
            "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        place_hold(hockey["id"])
        concert = draft_booking(
            riverton["id"], riverton_concert["id"], "Concert Sep 10",
            "2026-09-10T16:00:00Z", "2026-09-10T19:00:00Z",
            expected_attendance=8_000, rigging_load_kg=5_000,
            promoter_name="Northline Live",
        )
        place_hold(concert["id"])

        version_before = venue_version(lakeside["id"])
        response = api.create_changeover_order(
            {
                "from_booking_id": hockey["id"],
                "to_booking_id": concert["id"],
                "crew_headcount": 40,
                "expected_venue_version": version_before,
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_VENUE_SCOPE_MISMATCH.value, 409)

        _rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": lakeside["id"]})
        )
        assert meta["total_count"] == 0
        assert venue_version(lakeside["id"]) == version_before, (
            "a rejected create is not a mutation"
        )
