"""Capacity and scheduling guards: site windows, technician buffer, van water
capacity, vehicle capacity, discharge caps, route creation guards (PRD §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_stop_to_route, confirm_order,
    create_confirmed_order, create_customer, create_route, create_site,
    create_technician, create_van, create_vehicles, create_wash_order, get_order,
    get_route, get_van, route_event, set_clock, setup_customer_site_vehicles,
    validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestSiteWindowHalfOpenAdjacency:
    def _scenario(self):
        """Order A 13:00-14:00 CONFIRMED; B 14:00-15:00 and C 13:30-14:30 in DRAFT."""
        ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
        cid, sid, vids = ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"]
        order_a = create_confirmed_order(
            cid, sid, vids, scheduled_window_start="2026-08-06T13:00:00Z",
            scheduled_window_end="2026-08-06T14:00:00Z",
        )
        order_b = create_wash_order(
            cid, sid, vids, scheduled_window_start="2026-08-06T14:00:00Z",
            scheduled_window_end="2026-08-06T15:00:00Z",
        )
        order_c = create_wash_order(
            cid, sid, vids, scheduled_window_start="2026-08-06T13:30:00Z",
            scheduled_window_end="2026-08-06T14:30:00Z",
        )
        return order_a, order_b, order_c

    def test_touching_endpoints_do_not_conflict(self, api):
        """PRD §3.3: "the half-open window from `scheduled_window_start` up to but not
        including `scheduled_window_end` must not overlap any other order at the same
        site in `SCHEDULED`, `ASSIGNED`, or `IN_PROGRESS`, though touching endpoints
        (one order's end equal to another's start) do not conflict, and a violation is
        `ERR_SITE_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/site_window_half_open_adjacency
        """
        _, order_b, _ = self._scenario()
        confirmed = confirm_order(order_b["id"])
        assert confirmed["status"] == "SCHEDULED"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "the half-open window from `scheduled_window_start` up to but not
        including `scheduled_window_end` must not overlap any other order at the same
        site in `SCHEDULED`, `ASSIGNED`, or `IN_PROGRESS`, though touching endpoints
        (one order's end equal to another's start) do not conflict, and a violation is
        `ERR_SITE_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/site_window_half_open_adjacency
        """
        _, _, order_c = self._scenario()
        resp = api.wash_order_event(order_c["id"], {"event_type": "CONFIRM"},
                                    DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_SITE_WINDOW_CONFLICT)
        assert get_order(order_c["id"])["status"] == "DRAFT"


class TestTechnicianBufferExactly30Minutes:
    def _scenario(self):
        """Tech T1 leads R0 (default shift 08:00) whose stop for 3 sedans plans
        08:00-09:15; orders for the candidate routes are CONFIRMED."""
        customer = create_customer()
        site = create_site(customer["id"], name="PLAIN")
        sedans = create_vehicles(customer["id"], site["id"], 3, "SEDAN")
        suvs = create_vehicles(customer["id"], site["id"], 2, "SUV_PICKUP")
        o0 = create_confirmed_order(
            customer["id"], site["id"], sedans,
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T13:30:00Z",
        )
        o_gap30 = create_confirmed_order(
            customer["id"], site["id"], [sedans[0]] + suvs,
            scheduled_window_start="2026-08-05T13:30:00Z",
            scheduled_window_end="2026-08-05T14:30:00Z",
        )
        o_gap15 = create_confirmed_order(
            customer["id"], site["id"], [sedans[1]],
            scheduled_window_start="2026-08-05T14:30:00Z",
            scheduled_window_end="2026-08-05T15:00:00Z",
        )
        tech = create_technician(certified=True)
        van0 = create_van(name="VAN-B0", reclaim_system="BASIC", load_gallons=96)
        r0 = create_route("2026-08-05", van0["id"], tech["id"])
        add_stop_to_route(r0["id"], o0["id"])
        return {"tech": tech, "o_gap30": o_gap30, "o_gap15": o_gap15}

    def test_gap_exactly_30_minutes_admitted(self, api):
        """PRD §3.4: "Across different routes on the same date led by the same
        technician, the gap between one stop's `planned_end_at` and another stop's
        `planned_start_at` must be at least thirty minutes — exactly thirty is allowed
        — else `ERR_TECHNICIAN_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/technician_buffer_exactly_30_minutes
        """
        ctx = self._scenario()
        van2 = create_van(name="VAN-B2", reclaim_system="ADVANCED",
                          tank_capacity_gal=200, load_gallons=200)
        r2 = create_route("2026-08-05", van2["id"], ctx["tech"]["id"],
                          shift_start_at="2026-08-05T09:45:00Z")
        stop = add_stop_to_route(r2["id"], ctx["o_gap30"]["id"])
        assert stop["status"] == "PLANNED"
        assert stop["planned_start_at"] == "2026-08-05T09:45:00.000Z"
        # 15 setup + 20 + 25 + 25 = 85 minutes
        assert stop["planned_end_at"] == "2026-08-05T11:10:00.000Z"

    def test_gap_15_minutes_rejected(self, api):
        """PRD §3.4: "Across different routes on the same date led by the same
        technician, the gap between one stop's `planned_end_at` and another stop's
        `planned_start_at` must be at least thirty minutes — exactly thirty is allowed
        — else `ERR_TECHNICIAN_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/technician_buffer_exactly_30_minutes
        """
        ctx = self._scenario()
        van3 = create_van(name="VAN-B3", reclaim_system="NONE", load_gallons=100)
        r3 = create_route("2026-08-05", van3["id"], ctx["tech"]["id"],
                          shift_start_at="2026-08-05T09:30:00Z")
        route_now = get_route(r3["id"])
        resp = api.add_route_stop(
            r3["id"],
            {"wash_order_id": ctx["o_gap15"]["id"],
             "expected_route_version": route_now["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_SCHEDULE_CONFLICT)
        assert get_order(ctx["o_gap15"]["id"])["status"] == "SCHEDULED"


class TestVanWaterAggregateCapacityEquality:
    def _scenario(self):
        """Seven CONFIRMED 5-sedan orders; BASIC van loaded exactly 96 gal."""
        ctx = setup_customer_site_vehicles(num_vehicles=5, vehicle_class="SEDAN")
        orders = []
        slots = [("13:00:00", "13:30:00"), ("13:30:00", "14:00:00"),
                 ("14:00:00", "14:30:00"), ("14:30:00", "15:00:00"),
                 ("15:00:00", "15:30:00"), ("15:30:00", "16:00:00"),
                 ("16:00:00", "16:30:00")]
        for start, end in slots:
            orders.append(create_confirmed_order(
                ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
                scheduled_window_start=f"2026-08-05T{start}Z",
                scheduled_window_end=f"2026-08-05T{end}Z",
            ))
        van = create_van(name="VAN-WC", reclaim_system="BASIC", load_gallons=96)
        tech = create_technician()
        route = create_route("2026-08-05", van["id"], tech["id"])
        ctx.update({"orders": orders, "van": van, "route": route})
        return ctx

    def test_sixth_stop_lands_exactly_on_budget(self, api):
        """PRD §3.4: "Feasibility requires the van's free gallons — `water_loaded_gal`
        minus `water_used_gal` minus `water_reserved_gal` — to be at least the
        candidate stop's projected net draw, with equality allowed; otherwise the
        append fails with `ERR_ROUTE_WATER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/van_water_aggregate_capacity_equality
        """
        ctx = self._scenario()
        for order in ctx["orders"][:6]:
            add_stop_to_route(ctx["route"]["id"], order["id"])
        van = get_van(ctx["van"]["id"])
        # six 5-sedan stops: 6 x (40 gross x 0.4) = 96.0 == water_loaded_gal
        assert van["water_reserved_gal"] == 96.0
        assert get_route(ctx["route"]["id"])["assigned_vehicle_count"] == 30

    def test_seventh_stop_exceeds_budget(self, api):
        """PRD §3.4: "Feasibility requires the van's free gallons — `water_loaded_gal`
        minus `water_used_gal` minus `water_reserved_gal` — to be at least the
        candidate stop's projected net draw, with equality allowed; otherwise the
        append fails with `ERR_ROUTE_WATER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/van_water_aggregate_capacity_equality
        """
        ctx = self._scenario()
        for order in ctx["orders"][:6]:
            add_stop_to_route(ctx["route"]["id"], order["id"])
        route_now = get_route(ctx["route"]["id"])
        resp = api.add_route_stop(
            ctx["route"]["id"],
            {"wash_order_id": ctx["orders"][6]["id"],
             "expected_route_version": route_now["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_WATER_CAPACITY_EXCEEDED)
        assert get_order(ctx["orders"][6]["id"])["status"] == "SCHEDULED"


class TestDischargeCapEqualityAndExcess:
    def test_discharge_equal_to_cap_allowed_strictly_greater_rejected(self, api):
        """PRD §3.4: "then the projected discharge — gross gallons times the
        unrecovered fraction — must not exceed the site's `max_discharge_gal`, with a
        projection exactly equal to the cap allowed and anything strictly greater
        rejected with `ERR_DISCHARGE_CAP_EXCEEDED`."

        Design: Corner/calculations/discharge_cap_equality_and_excess
        """
        customer = create_customer()
        site16 = create_site(
            customer["id"], name="CAP16", lot_size_sqft=60000,
            containment_type="BERMS", water_reclaim_required=True, max_discharge_gal=16,
        )
        site10 = create_site(
            customer["id"], name="CAP10", lot_size_sqft=60000,
            containment_type="BERMS", water_reclaim_required=True, max_discharge_gal=10,
        )
        vehicles = create_vehicles(customer["id"], site16["id"], 5, "SEDAN")
        order16 = create_confirmed_order(
            customer["id"], site16["id"], vehicles,
            scheduled_window_start="2026-08-05T13:00:00Z",
            scheduled_window_end="2026-08-05T14:00:00Z",
        )
        order10 = create_confirmed_order(
            customer["id"], site10["id"], vehicles,
            scheduled_window_start="2026-08-06T13:00:00Z",
            scheduled_window_end="2026-08-06T14:00:00Z",
        )
        van = create_van(name="VAN-C5", reclaim_system="BASIC", load_gallons=96)
        tech = create_technician(certified=True)
        route_a = create_route("2026-08-05", van["id"], tech["id"])
        route_b = create_route("2026-08-06", van["id"], tech["id"])
        # BASIC recovery 0.60 -> projected discharge 40 x 0.4 = 16.0
        stop = add_stop_to_route(route_a["id"], order16["id"])
        assert stop["status"] == "PLANNED"
        assert stop["reserved_water_gal"] == 16.0
        route_b_now = get_route(route_b["id"])
        resp = api.add_route_stop(
            route_b["id"],
            {"wash_order_id": order10["id"],
             "expected_route_version": route_b_now["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_DISCHARGE_CAP_EXCEEDED)
        assert get_order(order10["id"])["status"] == "SCHEDULED"


class TestRouteVehicleCapacityAt41st:
    def test_44th_vehicle_rejected(self, api):
        """PRD §3.4: "And the route's `assigned_vehicle_count` plus the candidate
        order's `vehicle_count` must not exceed forty vehicles — exactly forty is
        allowed — else `ERR_ROUTE_VEHICLE_CAPACITY_EXCEEDED`."

        Design: Corner/errors/route_vehicle_capacity_at_41st
        """
        ctx = setup_customer_site_vehicles(num_vehicles=11, vehicle_class="SEDAN")
        slots = [("13:00:00", "13:30:00"), ("13:30:00", "14:00:00"),
                 ("14:00:00", "14:30:00"), ("14:30:00", "15:00:00")]
        orders = [
            create_confirmed_order(
                ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
                scheduled_window_start=f"2026-08-05T{start}Z",
                scheduled_window_end=f"2026-08-05T{end}Z",
            )
            for start, end in slots
        ]
        van = create_van(name="VAN-R6", reclaim_system="ADVANCED",
                         tank_capacity_gal=200, load_gallons=200)
        tech = create_technician(certified=True)
        route = create_route("2026-08-05", van["id"], tech["id"])
        for order in orders[:3]:
            add_stop_to_route(route["id"], order["id"])
        route_now = get_route(route["id"])
        assert route_now["assigned_vehicle_count"] == 33
        resp = api.add_route_stop(
            route["id"],
            {"wash_order_id": orders[3]["id"],
             "expected_route_version": route_now["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_VEHICLE_CAPACITY_EXCEEDED)
        assert get_order(orders[3]["id"])["status"] == "SCHEDULED"


class TestVanRouteConflictSameDate:
    def test_second_route_same_van_same_date_rejected(self, api):
        """PRD §3.4: "a van may appear on at most one non-terminal route per date —
        no other route with the same van and the same `route_date` may exist in
        `DRAFT`, `PUBLISHED`, or `LOCKED` (`ERR_VAN_ROUTE_CONFLICT`)"

        Design: Corner/validations/van_route_conflict_same_date
        """
        van = create_van(name="VAN-V5")
        tech = create_technician()
        first = create_route("2026-08-05", van["id"], tech["id"])
        assert first["status"] == "DRAFT"
        resp = api.create_route(
            {"route_date": "2026-08-05", "van_id": van["id"],
             "lead_technician_id": tech["id"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_VAN_ROUTE_CONFLICT)
        data, meta = validate_paginated(api.list_routes(DISPATCHER))
        assert meta["total_count"] == 1


class TestRouteCreateInactiveTechnician:
    def test_inactive_lead_rejected(self, api):
        """PRD §3.1: "Deactivation is prospective only: existing routes keep their
        lead, while creating a new route led by an inactive technician is rejected
        with `ERR_TECHNICIAN_NOT_ACTIVE`."

        Design: Corner/validations/route_create_inactive_technician
        """
        van = create_van(name="VAN-V4")
        tech = create_technician()
        validate_success(api.technician_event(
            tech["id"], {"event_type": "DEACTIVATE"}, ADMIN,
        ))
        resp = api.create_route(
            {"route_date": "2026-08-05", "van_id": van["id"],
             "lead_technician_id": tech["id"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_ACTIVE)


class TestAdvVanRequiresCertifiedLead:
    def test_uncertified_lead_rejected_then_admitted_after_certify(self, api):
        """PRD §3.4: "when the van's `reclaim_system` is `ADVANCED`, the lead
        technician must be `water_reclaim_certified` (`ERR_CERTIFICATION_REQUIRED`)"
        PRD §3.1: "The `CERTIFY_RECLAIM` event, valid on an active technician, sets
        `water_reclaim_certified` to true, qualifying that technician to lead routes
        on `ADVANCED`-reclaim vans."

        Design: Corner/errors/adv_van_requires_certified_lead
        """
        van = create_van(name="VAN-R4", reclaim_system="ADVANCED", tank_capacity_gal=200)
        tech = create_technician(certified=False)
        resp = api.create_route(
            {"route_date": "2026-08-05", "van_id": van["id"],
             "lead_technician_id": tech["id"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)
        validate_success(api.technician_event(
            tech["id"], {"event_type": "CERTIFY_RECLAIM"}, ADMIN,
        ))
        route = create_route("2026-08-05", van["id"], tech["id"])
        assert route["status"] == "DRAFT"
