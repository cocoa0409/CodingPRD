"""Rescheduling, weather credits, cancellation (PRD §3.9) and the logical clock (§2.10)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_confirmed_booking, get_booking, get_agent, get_photographer,
    reschedule, client_reschedule, weather_reschedule, live_version,
)


class TestRescheduleCap:
    def test_weather_at_cap_cancels_and_client_at_cap_rejected(self, api):
        """PRD §3.9: "A `CLIENT` reschedule attempted with `reschedule_count` already
        at three is refused with `ERR_RESCHEDULE_CAP_EXCEEDED` (HTTP 409). A `WEATHER`
        reschedule at the cap instead succeeds and cancels the shoot: the booking moves
        to `CANCELLED_WEATHER` with the same release cascade as a client cancellation,
        no per-event weather credit accrues, and a final weather-cancellation credit
        equal to one weather-credit application is granted into the agent's
        `credit_balance_cents`."

        Design: Corner/errors/error_reschedule_cap_exceeded_routes_to_cancellation
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48,
                               weather_reschedule_credit_bps=1000)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])

        def _at_cap(order_ref, address):
            booking = create_confirmed_booking(
                agent, photog, market["id"], order_ref=order_ref, property_address=address,
                equipment_package="STANDARD", photo_count=20,
                scheduled_start_utc="2026-08-05T14:00:00Z")
            # three in-cap CLIENT reschedules (quote 15000; CLIENT events credit zero)
            for new_start, reason in (("2026-08-06T14:00:00Z", "SELLER_DELAY"),
                                      ("2026-08-07T14:00:00Z", "ACCESS_ISSUE"),
                                      ("2026-08-08T14:00:00Z", "STAGING_DELAY")):
                booking = client_reschedule(booking, agent, new_start, reason)
                booking = get_success_data(api_client.confirm_booking(
                    booking["id"], make_coordinator_headers()))
            assert booking["reschedule_count"] == 3
            return booking

        # WEATHER at the cap: succeeds (200) and cancels the shoot
        weathered = _at_cap("ORD-CAP", "4 Cap Ave")
        resp = api_client.reschedule_booking(
            weathered["id"],
            {"expected_booking_version": live_version(weathered["id"]), "kind": "WEATHER",
             "new_start_utc": "2026-08-09T14:00:00Z", "reason_code": "WIND"},
            headers)
        cancelled = validate_success(resp)
        assert cancelled["state"] == "CANCELLED_WEATHER"
        assert cancelled["reschedule_count"] == 3  # terminal transition is not a reschedule
        # release cascade: photographer minutes released
        day_minutes = get_photographer(photog["id"])["committed_minutes_by_day"].get("2026-08-08", 0)
        assert day_minutes == 0
        # final cancellation credit = one weather-credit application: rhu(15000 * 0.10) = 1500
        assert get_agent(agent["id"])["credit_balance_cents"] == 1500

        # the terminal booking rejects any further reschedule
        resp = api_client.reschedule_booking(
            cancelled["id"],
            {"expected_booking_version": cancelled["version"], "kind": "CLIENT",
             "new_start_utc": "2026-08-20T14:00:00Z", "reason_code": "SELLER_DELAY"},
            headers)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_RESCHEDULABLE)

        # CLIENT at the cap on a twin booking: refused, no transition
        twin = _at_cap("ORD-CAP2", "5 Cap Ave")
        resp = api_client.reschedule_booking(
            twin["id"],
            {"expected_booking_version": live_version(twin["id"]), "kind": "CLIENT",
             "new_start_utc": "2026-08-09T14:00:00Z", "reason_code": "SELLER_DELAY"},
            headers)
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_CAP_EXCEEDED)
        assert get_booking(twin["id"])["state"] == "CONFIRMED"

    def test_invalid_reason_code_mismatched_kind(self, api):
        """PRD §3.9: "The reason code must match the kind: `PRECIPITATION`, `WIND`, or
        `LOW_LIGHT` for `WEATHER`, and `SELLER_DELAY`, `ACCESS_ISSUE`, or
        `STAGING_DELAY` for `CLIENT`; any mismatch fails with `ERR_INVALID_REASON_CODE`
        (HTTP 422)."

        Design: Corner/errors/error_invalid_reason_code_mismatched_kind
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-RC", property_address="6 Reason Rd",
            equipment_package="STANDARD", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")

        headers = make_client_agent_headers(agent["id"])
        resp = api_client.reschedule_booking(
            booking["id"],
            {"expected_booking_version": live_version(booking["id"]), "kind": "WEATHER",
             "new_start_utc": "2026-08-12T14:00:00Z", "reason_code": "SELLER_DELAY"},
            headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REASON_CODE)
        assert get_booking(booking["id"])["scheduled_start_utc"] == "2026-08-10T14:00:00Z"


class TestWeatherCreditCap:
    def test_weather_credit_capped_at_30_percent(self, api):
        """PRD §3.9: "accumulation is capped at thirty percent of the quote (3000 basis
        points, rounded half-up); the booking's `weather_credit_cents` becomes the
        smaller of the old accumulation plus the raw credit and the cap; and the event's
        `credit_applied_cents` records only the marginal amount this event actually
        contributed, so an event that lands on the cap may credit a partial amount or
        none at all."

        Quote 20625: per-event raw rhu(20625 * 0.10) = 2063; cap rhu(20625 * 0.30) =
        6188. After three events the credit is 6188 (NOT 6189) and the third event's
        marginal credit is clipped to 2062.

        Design: Corner/calculations/weather_credit_capped_at_30_percent
        """
        set_clock()
        market = create_market(market_code="ATX", display_name="Austin",
                               pricing_multiplier_bps=12500, standard_turnaround_hours=48,
                               weather_reschedule_credit_bps=1000)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        headers = make_client_agent_headers(agent["id"])

        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-WCAP",
            property_address="30 Cap Blvd", equipment_package="STANDARD", photo_count=30,
            scheduled_start_utc="2026-08-05T14:00:00Z")
        assert booking["provisional_quote_cents"] == 20625

        for new_start in ("2026-08-06T14:00:00Z", "2026-08-07T14:00:00Z",
                          "2026-08-08T14:00:00Z"):
            booking = weather_reschedule(booking, agent, new_start, "WIND")
            booking = get_success_data(api_client.confirm_booking(
                booking["id"], make_coordinator_headers()))

        assert booking["weather_credit_cents"] == 6188
        assert booking["reschedule_count"] == 3
        events = get_success_data(api_client.list_reschedule_events(booking["id"], headers))
        assert events[0]["credit_applied_cents"] == 2063
        assert events[1]["credit_applied_cents"] == 2063
        # marginal credit clipped: 6188 - 2*2063 = 2062
        assert events[2]["credit_applied_cents"] == 2062


class TestCancellation:
    def test_cancel_cutoff_12h_before_start(self, api):
        """PRD §3.9: "Cancelling a `CONFIRMED` booking carries one extra guard: the
        current moment must fall more than twelve hours before the scheduled start, or
        the request fails with `ERR_INSIDE_CANCELLATION_CUTOFF` (HTTP 422)."

        Design: Corner/endpoints/cancel_cutoff_12h_before_start
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(
            agent, photog, market["id"], order_ref="ORD-CUT", property_address="3 Cutoff Ct",
            equipment_package="STANDARD", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")

        # exactly start - 12h is not "more than twelve hours before"
        set_clock("2026-08-10T02:00:00Z")
        resp = api_client.cancel_booking(booking["id"], make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INSIDE_CANCELLATION_CUTOFF)
        assert get_booking(booking["id"])["state"] == "CONFIRMED"
        # failed cancel releases nothing
        assert get_photographer(photog["id"])["committed_minutes_by_day"]["2026-08-10"] == 60


class TestClockDrivenExpiry:
    def test_booking_expires_when_clock_reaches_start_in_draft(self, api):
        """PRD §3.1: "if the logical clock reaches `scheduled_start_utc` while the
        booking is still in `DRAFT`, the booking expires to `EXPIRED` and its checklist
        items freeze."
        PRD §2.10: "bookings still sitting in `DRAFT`, `AWAITING_READINESS`, or `READY`
        when the clock reaches their scheduled start expire on the spot ..."

        Design: Corner/complexity_layers/scheduled_system_transition_booking_expires
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-EXP",
                                 property_address="7 Expiry Ct",
                                 scheduled_start_utc="2026-08-05T14:00:00Z")

        set_clock("2026-08-05T14:00:00Z")
        expired = get_success_data(api_client.get_booking(
            booking["id"], make_client_agent_headers(agent["id"])))
        assert expired["state"] == "EXPIRED"

        resp = api_client.submit_booking(booking["id"], make_client_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_IN_DRAFT)
