"""Weather policy and water compliance: freeze cascades, incident-confirm cascade,
thresholds, hold expiry and reschedule windows (PRD §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_stop_to_route, confirm_incident,
    create_confirmed_order, create_customer, create_route, create_site,
    create_technician, create_van, create_vehicles, evaluate_weather, get_order,
    get_route, get_site, get_van, incident_event, list_route_stops, report_incident,
    set_clock, setup_customer_site_vehicles, stop_event, validate_error,
    validate_success,
)
from test_helpers.fixtures import route_event

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _freeze_scenario():
    """Two 5-sedan orders CONFIRMED on 2026-08-10; PUBLISHED route with both stops;
    BASIC van loaded 96 (each stop reserves 16.0)."""
    ctx = setup_customer_site_vehicles(num_vehicles=5, vehicle_class="SEDAN")
    o1 = create_confirmed_order(
        ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
        scheduled_window_start="2026-08-10T13:00:00Z",
        scheduled_window_end="2026-08-10T14:00:00Z",
    )
    o2 = create_confirmed_order(
        ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
        scheduled_window_start="2026-08-10T14:00:00Z",
        scheduled_window_end="2026-08-10T15:00:00Z",
    )
    van = create_van(name="VAN-W", load_gallons=96)
    tech = create_technician()
    route = create_route("2026-08-10", van["id"], tech["id"])
    s1 = add_stop_to_route(route["id"], o1["id"])
    s2 = add_stop_to_route(route["id"], o2["id"])
    route_event(route["id"], "PUBLISH")
    ctx.update({"o1": o1, "o2": o2, "van": van, "tech": tech, "route": route,
                "stops": (s1, s2)})
    return ctx


class TestWeatherFreezeCascade:
    def test_freeze_cancels_route_and_stops(self, api):
        """PRD §3.6: "every route whose `route_date` equals the evaluation date and
        whose status is `PUBLISHED` or `LOCKED` moves to `CANCELLED` with
        `cancel_reason` `WEATHER_FREEZE`; each such route's stops in `PLANNED` or
        `ARRIVED` move to `CANCELLED` and release their reserved water from the van"

        Design: Difficulty/transitive_cascade/weather_freeze_cascade
        """
        ctx = _freeze_scenario()
        assert get_van(ctx["van"]["id"])["water_reserved_gal"] == 32.0
        result = evaluate_weather("2026-08-10", 31, 10)
        assert result["freeze"] is True
        assert ctx["route"]["id"] in result["cancelled_route_ids"]
        route = get_route(ctx["route"]["id"])
        assert route["status"] == "CANCELLED"  # cascade link 1
        assert route["cancel_reason"] == "WEATHER_FREEZE"
        stops = list_route_stops(ctx["route"]["id"])
        assert all(s["status"] == "CANCELLED" for s in stops)  # link 2

    def test_freeze_holds_orders_and_releases_water(self, api):
        """PRD §3.6: "each of those stops' orders in `ASSIGNED` moves to
        `WEATHER_HELD` with `hold_reason` `WEATHER_FREEZE` and `held_at` stamped from
        the logical clock, the stop's water being released before the order's
        transition lands"

        Design: Difficulty/transitive_cascade/weather_freeze_cascade
        """
        ctx = _freeze_scenario()
        result = evaluate_weather("2026-08-10", 31, 10)
        assert ctx["o1"]["id"] in result["held_order_ids"]
        assert ctx["o2"]["id"] in result["held_order_ids"]
        o1 = get_order(ctx["o1"]["id"])
        assert o1["status"] == "WEATHER_HELD"  # link 3
        assert o1["hold_reason"] == "WEATHER_FREEZE"
        assert get_order(ctx["o2"]["id"])["status"] == "WEATHER_HELD"
        van = get_van(ctx["van"]["id"])
        assert van["water_reserved_gal"] == 0.0  # water released, none drawn
        assert van["water_used_gal"] == 0.0


class TestComplianceConfirmCascade:
    def _scenario(self):
        """O1 SCHEDULED unrouted; O2 ASSIGNED via PUBLISHED route (16.0 reserved);
        incident UNDER_REVIEW at the site."""
        ctx = setup_customer_site_vehicles(num_vehicles=5, vehicle_class="SEDAN")
        o1 = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-06T13:00:00Z",
            scheduled_window_end="2026-08-06T14:00:00Z",
        )
        o2 = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-06T14:00:00Z",
            scheduled_window_end="2026-08-06T15:00:00Z",
        )
        van = create_van(name="VAN-X", load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-06", van["id"], tech["id"])
        s2 = add_stop_to_route(route["id"], o2["id"])
        route_event(route["id"], "PUBLISH")
        incident = report_incident(ctx["site"]["id"], notes="soap runoff observed")
        incident_event(incident["id"], "START_REVIEW")
        ctx.update({"o1": o1, "o2": o2, "van": van, "route": route, "stop": s2,
                    "incident": incident})
        return ctx

    def test_confirm_suspends_site_and_cancels_unrouted_order(self, api):
        """PRD §3.7: "Moving an incident to `CONFIRMED` suspends the site with
        `suspension_reason` `COMPLIANCE_INCIDENT`, and the suspension cascades exactly
        as the site state machine dictates: every wash order at the site in
        `SCHEDULED` or `ASSIGNED` is cancelled with `cancel_reason` `SITE_SUSPENDED`"

        Design: Difficulty/transitive_cascade/compliance_confirm_cascade
        """
        ctx = self._scenario()
        incident_event(ctx["incident"]["id"], "CONFIRM")
        site = get_site(ctx["site"]["id"])
        assert site["status"] == "SUSPENDED"  # link 1
        assert site["suspension_reason"] == "COMPLIANCE_INCIDENT"
        o1 = get_order(ctx["o1"]["id"])
        assert o1["status"] == "CANCELLED"  # link 2 (unrouted)
        assert o1["cancel_reason"] == "SITE_SUSPENDED"

    def test_confirm_cancels_routed_order_stop_and_releases_water(self, api):
        """PRD §3.7: "each such assigned order's stop moves to `CANCELLED`; the stop's
        reserved water is released from the route's van, so `water_reserved_gal`
        decreases; and the route's `assigned_vehicle_count` and `reserved_water_gal`
        are recomputed."

        Design: Difficulty/transitive_cascade/compliance_confirm_cascade
        """
        ctx = self._scenario()
        incident_event(ctx["incident"]["id"], "CONFIRM")
        o2 = get_order(ctx["o2"]["id"])
        assert o2["status"] == "CANCELLED"  # link 2 (routed)
        assert o2["cancel_reason"] == "SITE_SUSPENDED"
        stops = list_route_stops(ctx["route"]["id"])
        assert stops[0]["status"] == "CANCELLED"  # link 3
        assert get_van(ctx["van"]["id"])["water_reserved_gal"] == 0.0
        assert get_route(ctx["route"]["id"])["assigned_vehicle_count"] == 0


class TestFreezeThresholdExactly32Degrees:
    def _published_route(self, route_date, window_date):
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start=f"{window_date}T13:00:00Z",
            scheduled_window_end=f"{window_date}T14:00:00Z",
        )
        van = create_van(load_gallons=96)
        tech = create_technician()
        route = create_route(route_date, van["id"], tech["id"])
        add_stop_to_route(route["id"], order["id"])
        route_event(route["id"], "PUBLISH")
        return route

    def test_exactly_32_freezes(self, api):
        """PRD §3.6: "A freeze triggers when `forecast_low_f` is at most 32 — 32
        exactly freezes, 33 does not."

        Design: Difficulty/boundary_precision_check/freeze_threshold_exactly_32_degrees
        """
        route = self._published_route("2026-08-20", "2026-08-20")
        result = evaluate_weather("2026-08-20", 32, 0)
        assert result["freeze"] is True
        assert get_route(route["id"])["status"] == "CANCELLED"

    def test_33_does_not_freeze(self, api):
        """PRD §3.6: "A freeze triggers when `forecast_low_f` is at most 32 — 32
        exactly freezes, 33 does not."

        Design: Difficulty/boundary_precision_check/freeze_threshold_exactly_32_degrees
        """
        route = self._published_route("2026-08-21", "2026-08-21")
        result = evaluate_weather("2026-08-21", 33, 0)
        assert result["freeze"] is False
        assert get_route(route["id"])["status"] == "PUBLISHED"


class TestRainAdvisoryThreshold60:
    def test_advisory_at_60_not_at_59_and_freeze_precedence(self, api):
        """PRD §3.6: "A rain advisory triggers when the low is above 32 and
        `precip_probability_pct` is at least 60 — 60 exactly raises the advisory, 59
        does not — setting `advisory` true without changing any order or route state."

        Design: Corner/calculations/rain_advisory_threshold_60
        """
        at_60 = evaluate_weather("2026-08-12", 40, 60)
        assert at_60["freeze"] is False
        assert at_60["advisory"] is True
        at_59 = evaluate_weather("2026-08-13", 40, 59)
        assert at_59["freeze"] is False
        assert at_59["advisory"] is False
        freeze_day = evaluate_weather("2026-08-14", 32, 90)
        assert freeze_day["freeze"] is True
        assert freeze_day["advisory"] is False


class TestWeatherHeldAutoExpireAfter14Days:
    def _held_order(self):
        """Order SCHEDULED for window date 2026-08-10, freeze-held at clock
        2026-08-10T08:00:00Z."""
        set_clock("2026-08-09T00:00:00Z")
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-10T13:00:00Z",
            scheduled_window_end="2026-08-10T14:00:00Z",
        )
        set_clock("2026-08-10T08:00:00Z")
        evaluate_weather("2026-08-10", 28, 0)
        return order

    def test_held_exactly_14_days_survives_day_15_expires(self, api):
        """PRD §3.6: "Orders still `WEATHER_HELD` whose `held_at` date plus fourteen
        days falls before the clock date are cancelled with `cancel_reason`
        `WEATHER_EXPIRED`; an order held exactly fourteen days is not expired."

        Design: Corner/calculations/weather_held_auto_expire_after_14_days
        """
        order = self._held_order()
        set_clock("2026-08-24T00:00:00Z")  # held date + 14
        sweep14 = validate_success(api.run_daily(DISPATCHER))
        assert order["id"] not in sweep14["expired_order_ids"]
        set_clock("2026-08-25T00:00:00Z")  # held date + 15
        sweep15 = validate_success(api.run_daily(DISPATCHER))
        assert order["id"] in sweep15["expired_order_ids"]
        final = get_order(order["id"])
        assert final["status"] == "CANCELLED"
        assert final["cancel_reason"] == "WEATHER_EXPIRED"


class TestRescheduleAfter14DaysExpired:
    def test_reschedule_on_day_15_rejected(self, api):
        """PRD §3.6: "Rescheduling a `WEATHER_HELD` order — by the owning customer or
        a dispatcher — requires the logical clock date to be no later than the
        `held_at` date plus fourteen days (the fourteenth day is allowed; later is
        `ERR_RESCHEDULE_WINDOW_EXPIRED`)"

        Design: Corner/validations/reschedule_after_14_days_expired
        """
        set_clock("2026-08-09T00:00:00Z")
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        order = create_confirmed_order(
            ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
            scheduled_window_start="2026-08-10T13:00:00Z",
            scheduled_window_end="2026-08-10T14:00:00Z",
        )
        set_clock("2026-08-10T08:00:00Z")
        evaluate_weather("2026-08-10", 28, 0)
        held = get_order(order["id"])
        assert held["status"] == "WEATHER_HELD"
        set_clock("2026-08-25T00:00:00Z")  # held 2026-08-10 + 14 = 2026-08-24 < clock
        resp = api.reschedule_wash_order(
            order["id"],
            {"scheduled_window_start": "2026-08-26T13:00:00Z",
             "scheduled_window_end": "2026-08-26T14:00:00Z",
             "expected_wash_order_version": held["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_WINDOW_EXPIRED)


class TestSiteReinstateGatedOnOpenIncidents:
    def test_reinstate_blocked_until_last_confirmed_incident_resolved(self, api):
        """PRD §3.7: "Reinstatement through the `REINSTATE` event is blocked while any
        incident at the site has status `CONFIRMED`, failing with
        `ERR_OPEN_COMPLIANCE_INCIDENT`; the system's own reinstatement on resolution
        simply does not fire while another incident at the site remains `CONFIRMED`."
        PRD §3.7: "Resolution moves `CONFIRMED` → `RESOLVED`; when no other incident
        at that site remains `CONFIRMED`, the system reinstates the site to `ACTIVE`
        and clears `suspension_reason`."

        Design: Corner/state_machines/site_reinstate_gated_on_open_incidents
        """
        customer = create_customer()
        site = create_site(customer["id"], name="S9S")
        inc1 = confirm_incident(site["id"], notes="first")
        inc2 = report_incident(site["id"], incident_type="CONTAINMENT_FAILURE",
                               notes="second")
        incident_event(inc2["id"], "START_REVIEW")
        incident_event(inc2["id"], "CONFIRM")
        resp = api.site_event(site["id"], {"event_type": "REINSTATE"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_OPEN_COMPLIANCE_INCIDENT)
        incident_event(inc1["id"], "RESOLVE")
        assert get_site(site["id"])["status"] == "SUSPENDED"
        incident_event(inc2["id"], "RESOLVE")
        reinstated = get_site(site["id"])
        assert reinstated["status"] == "ACTIVE"
        assert reinstated.get("suspension_reason") in (None, "")
