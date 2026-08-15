"""Booking intake: creation defaults, shape validation, pagination (PRD §3.1, §2.2-2.5)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    make_client_agent_headers, make_coordinator_headers, make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_booking_payload,
)


class TestBookingCreation:
    def test_create_applies_defaults_and_computes_duration(self, api):
        """PRD §3.1: "Optional intent flags ride along: `wants_virtual_tour` defaults to
        false ... `license_tier` of `MLS_COMPLIANT`, `STANDARD_MARKETING`, or `EXTENDED`
        defaults to `MLS_COMPLIANT` ... and `is_twilight` defaults to false. The server
        stamps the booking's `client_agent_id` from the caller's `X-User-ID` ... The
        booking is born in `DRAFT`, and the server immediately computes its
        `shoot_duration_minutes` and `scheduled_end_utc`."
        PRD §3.1: "The base length depends on the package: sixty minutes for `STANDARD` ..."

        Design: Corner/entities/booking_create_applies_defaults_and_computes_duration
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])

        resp = api_client.create_booking(
            create_booking_payload(
                market["id"], order_ref="ORD-DEF", property_address="1 Default Dr",
                equipment_package="STANDARD", photo_count=20,
                scheduled_start_utc="2026-08-10T14:00:00Z"),
            make_client_agent_headers(agent["id"]))
        booking = validate_success(resp, expected_status=201)

        assert booking["state"] == "DRAFT"
        assert booking["version"] == 1
        assert booking["wants_virtual_tour"] is False
        assert booking["license_tier"] == "MLS_COMPLIANT"
        assert booking["is_twilight"] is False
        assert booking["shoot_duration_minutes"] == 60
        assert booking["scheduled_end_utc"] == "2026-08-10T15:00:00Z"
        assert booking["client_agent_id"] == agent["id"]
        assert booking["reschedule_count"] == 0
        assert booking["revisions_used"] == 0
        assert booking["weather_credit_cents"] == 0

    def test_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.8: "Malformed requests — a missing required field, an invalid enum
        value, or otherwise malformed input — fail fast with `ERR_INVALID_REQUEST`
        (HTTP 400) before any business validation begins."

        Design: Corner/entities/booking_create_missing_required_field_returns_invalid_request
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])

        payload = {
            "order_ref": "ORD-BAD",
            "market_id": market["id"],
            # property_address omitted — required by PRD §3.1
            "equipment_package": "STANDARD",
            "photo_count": 20,
            "scheduled_start_utc": "2026-08-10T14:00:00Z",
        }
        resp = api_client.create_booking(payload, make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_invalid_enum_equipment_package_rejected(self, api):
        """PRD §3.1: "the contracted `equipment_package` of `STANDARD`, `PREMIUM`, or
        `LUXURY`" — any other value is an invalid enum value, which PRD §2.8 rejects
        with `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/booking_create_invalid_enum_equipment_package_rejected
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])

        payload = create_booking_payload(
            market["id"], order_ref="ORD-ENUM", property_address="2 Enum Ave",
            equipment_package="GOLD", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")
        resp = api_client.create_booking(payload, make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_booking_returns_not_found(self, api):
        """PRD §2.8: "3. **Existence** — unknown path identifiers or a broken parent
        chain fail with `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_nonexistent_booking_returns_not_found
        """
        set_clock()
        resp = api_client.get_booking(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


    def test_booking_initial_state_is_draft(self, api):
        """PRD §3.1: "The booking is born in `DRAFT`, and the server immediately
        computes its `shoot_duration_minutes` and `scheduled_end_utc`."
        PRD §3.1: "Submission locks the booking's `provisional_quote_cents` and
        spawns the property-readiness checklist ..."

        Design: Corner/state_machines/booking_initial_state_is_draft
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])

        resp = api_client.create_booking(
            create_booking_payload(
                market["id"], order_ref="ORD-INIT", property_address="11 Start St",
                equipment_package="PREMIUM", photo_count=40,
                scheduled_start_utc="2026-08-10T14:00:00Z"),
            make_client_agent_headers(agent["id"]))
        booking = validate_success(resp, expected_status=201)
        assert booking["state"] == "DRAFT"
        # the quote locks only at submission
        assert booking.get("provisional_quote_cents") is None


class TestPhotographerListing:
    def test_list_filter_by_market_and_pagination(self, api):
        """PRD §3.3: "Photographer listings can be filtered by `market_id` and
        `status`, and a reverse listing exposes the bookings assigned to a photographer,
        filterable by `state`."
        PRD §2.3: "The `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more` ..."

        Design: Corner/entities/photographer_list_filter_by_market_and_pagination
        """
        set_clock()
        den = create_market(market_code="DEN", display_name="Denver",
                            pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        atx = create_market(market_code="ATX", display_name="Austin",
                            pricing_multiplier_bps=12500, standard_turnaround_hours=48)
        create_photographer(den["id"], full_name="P One", email="p1@x.com")
        create_photographer(den["id"], full_name="P Two", email="p2@x.com")
        create_photographer(atx["id"], full_name="P Three", email="p3@x.com")

        resp = api_client.list_photographers(
            make_coordinator_headers(),
            params={"market_id": den["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, "limit=1 must be honored"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert all(p["market_id"] == den["id"] for p in data)
