"""Platform-wide rules and standing inventory: auth headers, RBAC denials,
not-found family, request shape, pagination envelope, the logical clock,
entity defaults, passenger derivation, and reverse reads (PRD §2, §3.1–§3.3)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_passenger,
    build_user_headers,
    create_booking,
    create_cruise,
    create_customer,
    create_menu_tier_payload,
    declare_weather_event,
    get_cruise,
    set_clock,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
    weather_cancel,
)

OM = TEST_USERS["ops_manager_headers"]
CAPTAIN = TEST_USERS["captain_headers"]
AGENT = TEST_USERS["charter_agent_headers"]


class TestAuthentication:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the
        acting user and `X-User-Role` to specify their operational capacity. A
        request missing either header, or carrying a malformed value, is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.create_dock(
            {"name": "Pier 9", "parking_capacity": 10},
            {"Content-Type": "application/json"})  # no X-User-ID / X-User-Role
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestFleetRbac:
    def test_customer_cannot_create_cruise(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the roles
        authorized for it in §4 is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST | `/cruises` | Schedule a cruise | OperationsManager"

        Design: Corner/rbac/customer_cannot_create_cruise
        """
        inv = setup_inventory()
        resp = api.create_cruise(
            {"vessel_id": inv["vessel"]["id"],
             "menu_tier_id": inv["tier"]["id"],
             "depart_at": "2026-08-10T19:00:00Z",
             "return_at": "2026-08-10T22:00:00Z"},
            build_user_headers("some-customer", "Customer"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_captain_cannot_weather_cancel(self, api):
        """PRD §2.1: "`Captain` is the vessel master and owns manifest
        freeze/amend plus departure and completion."
        PRD §2.1: "An attempt to perform an operation outside the roles
        authorized for it in §4 is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST | `/cruises/{id}/weather-cancel` | Weather-cancel a cruise
        | OperationsManager"

        Design: Corner/rbac/captain_cannot_weather_cancel
        """
        inv = setup_inventory()
        declare_weather_event()
        resp = api.weather_cancel_cruise(inv["cruise"]["id"], CAPTAIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestNotFoundFamily:
    def test_get_nonexistent_cruise_returns_not_found(self, api):
        """PRD §2.7: "a cruise, `ERR_CRUISE_NOT_FOUND`"
        PRD §2.7: "All sixteen are HTTP 404."

        Design: Corner/entities/get_nonexistent_cruise_returns_not_found
        """
        resp = api.get_cruise(NON_EXISTENT_UUID, OM)
        validate_error(resp, ApiErrorId.ERR_CRUISE_NOT_FOUND)


class TestRequestShape:
    def test_invalid_menu_tier_code_rejected(self, api):
        """PRD §2.8: "a malformed JSON body, an unrecognized enum value in any
        field, a missing required field, or an inverted time range ... is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A **MenuTier** carries a `code` of `STANDARD`, `PREMIUM`, or
        `LUXE`"

        Design: Corner/entities/invalid_enum_menu_tier_code_rejected
        """
        resp = api.create_menu_tier(
            create_menu_tier_payload(code="DELUXE"), OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_cruise_return_before_depart_rejected(self, api):
        """PRD §3.2: "The return must be strictly later than the departure, or
        the request fails as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/cruise_return_before_depart_rejected
        """
        inv = setup_inventory()
        resp = api.create_cruise(
            {"vessel_id": inv["vessel"]["id"],
             "menu_tier_id": inv["tier"]["id"],
             "depart_at": "2026-08-10T22:00:00Z",
             "return_at": "2026-08-10T19:00:00Z"},
            OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPaginationAndListing:
    def test_list_envelope_and_defaults(self, api):
        """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1
        and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_envelope_and_defaults
        """
        setup_inventory()
        resp = api.list_cruises(OM)
        body = resp.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"].startswith("req_")
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"Default limit must be 10, got {meta['limit']}"
        )
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1

    def test_list_filter_by_status(self, api):
        """PRD §2.3: "The cruise list may be narrowed by `status` or
        `vessel_id`"

        Design: Corner/endpoints/list_filter_by_status
        """
        inv = setup_inventory()
        cr1 = inv["cruise"]
        cr2 = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                            depart_at="2026-08-12T19:00:00Z",
                            return_at="2026-08-12T22:00:00Z")
        declare_weather_event()
        weather_cancel(cr1["id"])
        assert get_cruise(cr1["id"])["status"] == "CANCELLED"
        assert get_cruise(cr2["id"])["status"] == "SCHEDULED"

        data, meta = validate_paginated(api.list_cruises(
            OM, params={"status": "CANCELLED"}))
        ids = [c["id"] for c in data]
        assert ids == [cr1["id"]], (
            f"Only the cancelled cruise must be returned, got {ids}"
        )
        assert meta["total_count"] == 1


class TestLogicalClock:
    def test_clock_set_reports_new_reading(self, api):
        """PRD §2.4: "Before any call to set it, the logical clock reads exactly
        `2026-08-01T00:00:00Z` — a fixed startup default. An `OperationsManager`
        may advance or set the clock through an admin-only test-driving
        capability whose request body carries a `to_iso8601` timestamp; the
        response reports the resulting reading as `current_utc`."

        Design: Corner/complexity_layers/clock_default_and_set
        """
        data = set_clock("2026-08-05T00:00:00Z")
        # PRD pins the reported reading, not its string rendering — compare
        # instants.
        actual = datetime.fromisoformat(data["current_utc"].replace("Z", "+00:00"))
        assert actual == datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc), (
            f"After set, current_utc must report the new reading, got "
            f"{data['current_utc']}"
        )


class TestEntityDefaults:
    def test_vessel_creation_applies_default_status(self, api):
        """PRD §3.1: "A vessel's `status` is `ACTIVE` when created."
        PRD §2.5: "`version` (integer): a system-managed integer that increments
        by one on every modification of the resource, including modifications
        driven by cascades and by recomputation of derived fields."

        Design: Corner/entities/vessel_creation_applies_default_status
        """
        inv = setup_inventory()
        vessel = inv["vessel"]
        assert vessel["status"] == "ACTIVE", (
            f"A new vessel must default to ACTIVE, got {vessel['status']}"
        )
        assert vessel["version"] == 1
        assert vessel["created_at"] is not None

    def test_out_of_service_vessel_rejects_cruise_scheduling(self, api):
        """PRD §3.1: "Taking a vessel out of service moves it from `ACTIVE` to
        `OUT_OF_SERVICE`; scheduling a cruise on a vessel that is not `ACTIVE` is
        rejected with `ERR_VESSEL_OUT_OF_SERVICE` (rung 17)."

        Design: Corner/validations/cruise_on_out_of_service_vessel_rejected
        """
        inv = setup_inventory()
        taken_out = validate_success(
            api.set_vessel_out_of_service(inv["vessel"]["id"], OM))
        assert taken_out["status"] == "OUT_OF_SERVICE"
        resp = api.create_cruise(
            {"vessel_id": inv["vessel"]["id"],
             "menu_tier_id": inv["tier"]["id"],
             "depart_at": "2026-08-10T19:00:00Z",
             "return_at": "2026-08-10T22:00:00Z"},
            OM)
        validate_error(resp, ApiErrorId.ERR_VESSEL_OUT_OF_SERVICE)


class TestPassengerRecords:
    def test_is_minor_derived_from_departure_date(self, api):
        """PRD §3.3: "From the date of birth the server derives `is_minor`: true
        when the passenger's age at the cruise's scheduled departure instant is
        under twenty-one years — the US alcohol-service benchmark — and this flag
        drives alcohol-service denial."
        PRD §2.4: "One age rule deliberately does not read the clock: a
        passenger's minor status is measured against the cruise's scheduled
        departure instant, not against "now" (see §3.3)."

        Design: Corner/entities/passenger_is_minor_computed_from_depart_date
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 2,
                                 cruise["version"])
        kid = add_passenger(booking["id"], customer["id"], "Kid", "2008-01-01")
        adult = add_passenger(booking["id"], customer["id"], "Adult",
                              "2000-01-01")
        # Departure 2026-08-10: born 2008-01-01 is 18 (minor); born 2000-01-01
        # is 26 (not a minor).
        assert kid["is_minor"] is True
        assert adult["is_minor"] is False

    def test_passenger_record_carries_no_version_field(self, api):
        """PRD §2.5: "A booking passenger record and a cruise credit record
        carry only `id` and `created_at`; both `updated_at` and `version` are
        absent on those two resources."

        Design: Corner/entities/booking_passenger_immutable_no_version_field
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 1,
                                 cruise["version"])
        passenger = add_passenger(booking["id"], customer["id"], "P1",
                                  "1990-01-01")
        assert passenger.get("id")
        assert passenger.get("created_at")
        assert "version" not in passenger, (
            "BookingPassenger must not carry a version field"
        )
        assert "updated_at" not in passenger


class TestReverseReads:
    def test_bookings_discoverable_from_customer(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id`
        of the acting Customer record; ownership checks on any resource that
        references a Customer compare the resource's customer foreign-key field
        to `X-User-ID`."
        PRD §4: "GET | `/customers/{id}/bookings` | List a customer's bookings"

        Design: Corner/endpoints/fk_reverse_reachability_customer_bookings
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 1,
                                 cruise["version"])
        data, meta = validate_paginated(api.list_customer_bookings(
            customer["id"], OM))
        ids = [b["id"] for b in data]
        assert ids == [booking["id"]], (
            f"The customer's booking list must contain exactly the created "
            f"booking, got {ids}"
        )
