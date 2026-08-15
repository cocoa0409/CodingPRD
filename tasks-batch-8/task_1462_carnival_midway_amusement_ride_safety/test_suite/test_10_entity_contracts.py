"""Entity and envelope contracts: required/computed field rejection, server
defaults, the startup logical clock, 404s, pagination, the append-only weather
log, ride initial state, immediate read-after-write consistency, and the
authentication gate (PRD sections 2.1-2.5, 2.10, 3.1, 3.2).

Covers design instances:
  Corner/entities/ride_create_missing_ride_class_returns_400
  Corner/entities/inspector_defaults_applied_when_optional_fields_omitted
  Corner/entities/fair_create_with_computed_field_rejected
  Corner/entities/system_fields_server_minted_against_default_clock
  Corner/entities/ride_get_not_found_returns_404
  Corner/entities/list_pagination_defaults_and_envelope
  Corner/entities/weather_observation_is_append_only_without_version
  Corner/state_machines/ride_initial_state_defaults
  Corner/consistency_model/mutation_visible_immediately_in_response_and_version_increments
  Corner/validations/missing_auth_headers_returns_unauthenticated
  Corner/validations/existence_beats_business_on_unknown_path_id
  Corner/endpoints/rides_filtered_list_reverse_lookup_by_fair
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_observation,
    assert_ride,
    create_fair_payload,
    create_ride_payload,
    is_valid_uuid,
    make_admin_headers,
    make_crew_headers,
    make_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


class TestRequestShape:
    def test_ride_create_missing_ride_class_returns_400(self, api):
        """PRD section 2.10: "Required fields present, types and enum
        membership valid, numeric ranges honored (hours, heights, quantities,
        capacities), the fair date ordering respected, ... — any violation
        yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/ride_create_missing_ride_class_returns_400
        """
        ctx = fx.setup_fair_with_staff("E1")
        sup = ctx["sup"]
        payload = create_ride_payload(sup["fair_id"], serial_number="SN-E1-1")
        payload.pop("ride_class")
        resp = api.create_ride(payload, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        data, meta = validate_paginated(api.list_rides(
            make_manager_headers(sup["id"]), params={"fair_id": sup["fair_id"]}))
        assert meta["total_count"] == 0 and data == [], (
            "a rejected create must persist nothing")

    def test_fair_create_with_computed_field_rejected(self, api):
        """PRD section 2.10: "no unknown or server-computed fields supplied —
        any violation yields `ERR_INVALID_REQUEST` (400)." The fair's `status`
        is system-managed (PRD section 3.1: "A new fair starts in `SETUP`
        status") and may not be supplied by the caller.

        Design: Corner/entities/fair_create_with_computed_field_rejected
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        payload = create_fair_payload(name="Hack Fair", location="Lot X",
                                      midway_capacity=100)
        payload["status"] = "PERMITTED"
        resp = api.create_fair(payload, make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestServerManagedFields:
    def test_inspector_defaults_applied_when_optional_fields_omitted(self, api):
        """PRD section 3.2: "An optional `max_daily_inspections` caps the
        inspector's appointment load per day; when omitted it defaults to 3,
        and in all cases it must sit between 1 and 8. New inspectors are
        `active` by default."

        Design: Corner/entities/inspector_defaults_applied_when_optional_fields_omitted
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        insp = fx.create_inspector("LIC-DF-1", full_name="Default Insp")
        assert insp["max_daily_inspections"] == 3
        assert insp["active"] is True

    def test_system_fields_server_minted_against_default_clock(self, api):
        """PRD section 2.4: "At startup the logical clock is exactly
        `2026-08-01T00:00:00Z`." PRD section 2.5: "`created_at` (string): an
        ISO 8601 UTC timestamp with three fractional digits, set once at
        creation." PRD section 3.1: "A new fair starts in `SETUP` status".

        Design: Corner/entities/system_fields_server_minted_against_default_clock
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        fair = fx.create_fair(name="Clock Fair", location="Lot C",
                              midway_capacity=100)
        assert fair["created_at"] == "2026-08-01T00:00:00.000Z", (
            f"created_at must be stamped from the pinned logical clock; got "
            f"{fair['created_at']}")
        assert fair["status"] == "SETUP"
        assert is_valid_uuid(fair["id"])
        assert isinstance(fair["version"], int)

    def test_ride_get_not_found_returns_404(self, api):
        """PRD section 2.10: "Path identifiers must resolve, validated left to
        right; the first unresolvable identifier yields `ERR_NOT_FOUND` (404)
        before any later segment is examined."

        Design: Corner/entities/ride_get_not_found_returns_404
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        resp = api.get_ride(NON_EXISTENT_UUID, make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestListEnvelope:
    def test_list_pagination_defaults_and_envelope(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned; when omitted it defaults to 10, and it is bounded below by 1
        and above by 100. The `offset` parameter skips a number of items from
        the start of the result set and defaults to 0... The `meta` object of
        list responses carries the pagination fields `limit`, `offset`,
        `total_count`, and `has_more`." PRD section 2.2: "The `response_type`
        is either "object" for a single resource or "array" for a list of
        resources."

        Design: Corner/entities/list_pagination_defaults_and_envelope
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        fx.create_fair(name="Fair One", location="Lot A", midway_capacity=100)
        fx.create_fair(name="Fair Two", location="Lot B", midway_capacity=100)
        resp = api.list_fairs(make_admin_headers(), params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert isinstance(resp.json()["meta"].get("api_request_id"), str)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        data_all, meta_all = validate_paginated(api.list_fairs(make_admin_headers()))
        assert meta_all["limit"] == 10, "the default limit is 10"
        assert len(data_all) == 2
        assert meta_all["has_more"] is False


class TestWeatherObservationContract:
    def test_observation_is_append_only_without_version(self, api):
        """PRD section 2.5: "One entity is deliberately exempt:
        **WeatherObservation** records are append-only and carry only `id` and
        `created_at` — both `updated_at` and `version` are absent from them."
        PRD section 3.7: "every ride whose `daily_status` is `OPEN` and whose
        own `wind_limit_mph` is met or exceeded by the reading moves to
        `WEATHER_HOLD`" — a 12 mph reading with no OPEN ride sweeps nothing.

        Design: Corner/entities/weather_observation_is_append_only_without_version
        """
        ctx = fx.setup_permitted_fair("E7")
        fx.begin_day(ctx)  # CHECKLIST_PHASE; rides were never opened
        obs = fx.record_wind(ctx["sup"], ctx["day"]["id"], 12)
        assert_observation(obs)
        assert obs["operating_day_id"] == ctx["day"]["id"]
        assert obs["wind_speed_mph"] == 12
        ride = fx.get_ride(ctx["sup"], ctx["ride"]["id"])
        assert ride["daily_status"] == "CLOSED"


class TestRideInitialState:
    def test_ride_initial_state_defaults(self, api):
        """PRD section 3.1: "A new ride starts with `setup_status` `INSTALLED`,
        `license_status` `PENDING`, and `daily_status` `CLOSED`, with both of
        its counters — `cycles_since_inspection` and `minor_incidents_today` —
        at zero."

        Design: Corner/state_machines/ride_initial_state_defaults
        """
        ctx = fx.setup_fair_with_staff("SM3")
        sup = ctx["sup"]
        ride = fx.create_ride(sup, ride_class="EXTREME", capacity_per_cycle=2,
                              min_rider_height_in=52, max_rider_height_in=84,
                              wind_limit_mph=20, cycle_inspection_interval=2,
                              serial_number="SN-SM3-1")
        assert_ride(ride)
        assert ride["setup_status"] == "INSTALLED"
        assert ride["license_status"] == "PENDING"
        assert ride["daily_status"] == "CLOSED"
        assert ride["cycles_since_inspection"] == 0
        assert ride["minor_incidents_today"] == 0
        assert isinstance(ride["version"], int)


class TestImmediateConsistency:
    def test_mutation_visible_in_response_and_version_increments(self, api):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field." PRD section 2.5: "`version` (integer): a
        system-managed integer that increments by exactly one on every mutation
        of the resource, including mutations produced by cascades and
        derived-field recomputation."

        The verify-assembly response already shows the new state with the
        version advanced by one, and an immediate GET returns identical values.

        Design: Corner/consistency_model/mutation_visible_immediately_in_response_and_version_increments
        """
        ctx = fx.setup_fair_with_staff("CM1")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew CM1", ["CREW"])
        ride = fx.create_ride(sup, serial_number="SN-CM1-1")
        fx.book_setup_shift(sup, crew)
        verified = validate_success(api.verify_assembly(
            ride["id"], {}, make_crew_headers(crew["id"])))
        assert verified["setup_status"] == "SETUP_VERIFIED"
        assert verified["version"] == ride["version"] + 1, (
            "the mutation must advance the version by exactly one")
        fetched = fx.get_ride(sup, ride["id"])
        assert fetched["setup_status"] == verified["setup_status"]
        assert fetched["version"] == verified["version"], (
            "a read immediately after the mutation must see the same state")


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD section 2.1: "Missing or blank headers are rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        resp = api.create_fair(create_fair_payload(name="NoAuth Fair",
                                                   location="Lot Z",
                                                   midway_capacity=100), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_existence_beats_business_on_unknown_path_id(self, api):
        """PRD section 2.10: "Every request is evaluated against a fixed
        pipeline of check families, and the first failure stops the pipeline —
        later families are never consulted." and "4. **Path resolution (all
        endpoints with path parameters).** Path identifiers must resolve,
        validated left to right; the first unresolvable identifier yields
        `ERR_NOT_FOUND` (404) before any later segment is examined."

        The caller also lacks a covering shift, but the unknown ride id must
        surface ERR_NOT_FOUND first.

        Design: Corner/validations/existence_beats_business_on_unknown_path_id
        """
        ctx = fx.setup_fair_with_staff("V2")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew V2", ["CREW"])
        resp = api.verify_assembly(NON_EXISTENT_UUID, {}, make_crew_headers(crew["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestRidesReverseLookup:
    def test_rides_filtered_list_reverse_lookup_by_fair(self, api):
        """PRD section 2.8: "Related resources are joined by identifier fields
        in request bodies and, for reverse lookups, by query-parameter filters
        on the list endpoints." and "Rides filter by `fair_id`, `setup_status`,
        `license_status`, and `daily_status`."

        Design: Corner/endpoints/rides_filtered_list_reverse_lookup_by_fair
        """
        fx.set_clock(fx.SETUP_DAY_ISO)
        fair_a = fx.create_fair(name="Fair A", location="Lot A")
        fair_b = fx.create_fair(name="Fair B", operator_company_name="OtherCo",
                                location="Lot B")
        sup_a = fx.create_supervisor(fair_a["id"], full_name="Sup A")
        sup_b = fx.create_supervisor(fair_b["id"], full_name="Sup B")
        ride_a = fx.create_ride(sup_a, name="Ride A", ride_class="KIDDIE",
                                capacity_per_cycle=6, min_rider_height_in=30,
                                max_rider_height_in=60, wind_limit_mph=35,
                                cycle_inspection_interval=10,
                                serial_number="SN-EP-1")
        ride_b = fx.create_ride(sup_b, name="Ride B", ride_class="EXTREME",
                                capacity_per_cycle=2, min_rider_height_in=52,
                                max_rider_height_in=84, wind_limit_mph=20,
                                cycle_inspection_interval=2,
                                serial_number="SN-EP-2")
        data, meta = validate_paginated(api.list_rides(
            make_manager_headers(sup_a["id"]), params={"fair_id": fair_a["id"]}))
        assert meta["total_count"] == 1 and len(data) == 1
        assert data[0]["id"] == ride_a["id"]
        assert ride_b["id"] not in [r["id"] for r in data], (
            "fair B's ride must never leak into fair A's filtered list")
