"""Route days, dispatch constraints, mechanic overlap, and resequencing."""
from test_helpers import (
    ApiErrorId,
    get_request,
    get_route_day,
    make_bike,
    make_customer,
    make_mechanic,
    make_van,
    setup_dispatched_request,
    setup_quoted_request,
    setup_two_stop_route_day,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRouteDayLifecycle:
    def test_route_day_lock_unlock_revert(self, api, dispatcher_headers):
        """PRD §3.6: "Locking moves `OPEN` to `LOCKED`, and unlocking reverses it —
        a deliberately non-linear revert for plan-then-freeze workflows."

        Design: Corner/state_machines/route_day_lock_unlock_revert
        """
        ctx = setup_quoted_request()
        mech = make_mechanic(ctx["zone"]["id"])
        van = make_van(ctx["zone"]["id"], mechanic_id=mech["id"])
        rd = validate_success(api.create_route_day(
            {"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers), 201)
        assert rd["status"] == "OPEN"

        locked = validate_success(api.route_day_event(rd["id"], {"event_type": "LOCK"}, dispatcher_headers), 200)
        assert locked["status"] == "LOCKED"
        reopened = validate_success(api.route_day_event(rd["id"], {"event_type": "UNLOCK"}, dispatcher_headers), 200)
        assert reopened["status"] == "OPEN"

    def test_duplicate_route_day_rejected(self, api, dispatcher_headers):
        """PRD §3.6: "One route day per van per date is allowed — a duplicate pair
        is refused with `ERR_ROUTE_DAY_EXISTS` (HTTP 409)"

        Design: Corner/errors/duplicate_route_day_rejected
        """
        ctx = setup_quoted_request()
        van = make_van(ctx["zone"]["id"])
        validate_success(api.create_route_day({"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers), 201)
        resp = api.create_route_day({"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_EXISTS)

    def test_route_day_for_out_of_service_van_rejected(self, api, dispatcher_headers):
        """PRD §3.3: "Taking a van out of service moves it to `OUT_OF_SERVICE` and
        blocks both new route days and new stop additions for it (surfaced as
        `ERR_VAN_UNAVAILABLE`, HTTP 409)"

        Design: Corner/validations/route_day_for_out_of_service_van_rejected
        """
        ctx = setup_quoted_request()
        mech = make_mechanic(ctx["zone"]["id"])
        van = make_van(ctx["zone"]["id"], mechanic_id=mech["id"])
        validate_success(api.van_event(van["id"], {"event_type": "TAKE_OUT_OF_SERVICE"}, dispatcher_headers), 200)
        resp = api.create_route_day({"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_VAN_UNAVAILABLE)


class TestDispatchConstraints:
    def test_route_capacity_boundary_rejected(self, api, dispatcher_headers):
        """PRD §3.6: "the day's `active_stop_count` must still be below the van's
        `max_stops_per_day`, else `ERR_ROUTE_CAPACITY_EXCEEDED` (all HTTP 409)."

        Design: Corner/validations/route_capacity_boundary_rejected
        """
        zone_ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        # Second customer so the customer-overlap rule cannot interfere.
        bob = make_customer("INDIVIDUAL")
        bob_bike = make_bike(bob["id"])
        req2 = validate_success(api.create_service_request({
            "customer_id": bob["id"], "bike_id": bob_bike["id"],
            "zone_id": zone_ctx["zone"]["id"], "tier_id": zone_ctx["tier"]["id"],
            "window_start": "2026-05-02T12:00:00Z", "window_end": "2026-05-02T13:00:00Z",
        }, dispatcher_headers), 201)
        mech = make_mechanic(zone_ctx["zone"]["id"])
        van = make_van(zone_ctx["zone"]["id"], mechanic_id=mech["id"], max_stops_per_day=1)
        rd = validate_success(api.create_route_day({"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers), 201)
        # First stop fits: active_stop_count 0 < 1.
        validate_success(api.create_route_stop(rd["id"], {
            "service_request_id": zone_ctx["request"]["id"],
            "planned_start": "2026-05-02T10:00:00Z", "planned_end": "2026-05-02T10:30:00Z",
        }, dispatcher_headers), 201)
        # Second stop: active_stop_count == max_stops_per_day == 1.
        resp = api.create_route_stop(rd["id"], {
            "service_request_id": req2["id"],
            "planned_start": "2026-05-02T12:00:00Z", "planned_end": "2026-05-02T12:30:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)

    def test_ebike_dispatch_requires_certified_mechanic(self, api, dispatcher_headers):
        """PRD §3.6: "an `EBIKE` job requires the assigned mechanic to hold
        `ebike_certified`, else `ERR_MECHANIC_NOT_EBIKE_CERTIFIED`"

        Design: Corner/validations/ebike_dispatch_requires_certified_mechanic
        """
        ctx = setup_quoted_request(bike={"bike_type": "EBIKE", "battery_wh": 500,
                                         "battery_certified": True, "battery_health_pct": 95})
        mech = make_mechanic(ctx["zone"]["id"], ebike_certified=False)
        van = make_van(ctx["zone"]["id"], mechanic_id=mech["id"])
        rd = validate_success(api.create_route_day({"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers), 201)
        resp = api.create_route_stop(rd["id"], {
            "service_request_id": ctx["request"]["id"],
            "planned_start": "2026-05-02T10:00:00Z", "planned_end": "2026-05-02T11:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_MECHANIC_NOT_EBIKE_CERTIFIED)
        assert get_request(ctx["request"]["id"])["work_status"] == "QUOTED"


class TestDispatchRequiresActiveMechanic:
    def _setup_suspended_mechanic(self, api, dispatcher_headers):
        ctx = setup_quoted_request()
        mech = make_mechanic(ctx["zone"]["id"])
        van = make_van(ctx["zone"]["id"], mechanic_id=mech["id"])
        rd = validate_success(api.create_route_day({"van_id": van["id"], "date": "2026-05-02"}, dispatcher_headers), 201)
        validate_success(api.mechanic_event(mech["id"], {"event_type": "SUSPEND", "reason": "injury"}, dispatcher_headers), 200)
        return ctx, mech, rd

    def test_dispatch_with_suspended_mechanic_rejected(self, api, dispatcher_headers):
        """PRD §3.6: "the assigned mechanic must be `ACTIVE`, else
        `ERR_MECHANIC_SUSPENDED`"

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_mechanic_active
        """
        ctx, mech, rd = self._setup_suspended_mechanic(api, dispatcher_headers)
        resp = api.create_route_stop(rd["id"], {
            "service_request_id": ctx["request"]["id"],
            "planned_start": "2026-05-02T10:00:00Z", "planned_end": "2026-05-02T11:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_MECHANIC_SUSPENDED)

    def test_rejected_dispatch_leaves_request_quoted_and_day_empty(self, api, dispatcher_headers):
        """PRD §3.6: "the assigned mechanic must be `ACTIVE`, else
        `ERR_MECHANIC_SUSPENDED`"
        PRD §3.6: "A successful dispatch creates the stop in `PLANNED` with `seq`
        equal to the day's `active_stop_count` plus one, moves the request from
        `QUOTED` to `DISPATCHED`" — so a rejected dispatch creates no stop and
        leaves the request `QUOTED`.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_mechanic_active
        """
        ctx, mech, rd = self._setup_suspended_mechanic(api, dispatcher_headers)
        validate_error(api.create_route_stop(rd["id"], {
            "service_request_id": ctx["request"]["id"],
            "planned_start": "2026-05-02T10:00:00Z", "planned_end": "2026-05-02T11:00:00Z",
        }, dispatcher_headers), ApiErrorId.ERR_MECHANIC_SUSPENDED)
        req = get_request(ctx["request"]["id"])
        assert req["work_status"] == "QUOTED"
        assert req["scheduled_mechanic_id"] is None
        day = get_route_day(rd["id"])
        assert day["active_stop_count"] == 0
        stops, _ = validate_paginated(api.list_route_day_stops(rd["id"], dispatcher_headers))
        assert stops == [], f"no stop may be created by a rejected dispatch, got {stops}"


class TestMechanicBufferedOverlap:
    def _setup_one_stop(self, api, dispatcher_headers):
        """One PLANNED stop 10:00-11:00 for mechanic Mo; a second customer's
        QUOTED request with window 10:30-13:00 ready to dispatch."""
        ctx = setup_dispatched_request(
            window=("2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z"),
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        bob = make_customer("INDIVIDUAL")
        bob_bike = make_bike(bob["id"])
        req2 = validate_success(api.create_service_request({
            "customer_id": bob["id"], "bike_id": bob_bike["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T10:30:00Z", "window_end": "2026-05-02T13:00:00Z",
        }, dispatcher_headers), 201)
        return ctx, req2

    def test_start_inside_buffer_conflicts(self, api, dispatcher_headers):
        """PRD §3.6: "the new stop occupies the span from `planned_start` minus its
        buffer to `planned_end` plus its buffer, and it conflicts with any existing
        `PLANNED` or `ARRIVED` stop assigned to the same mechanic — across every
        route day of that mechanic's vans — when the expanded new start is strictly
        before the existing stop's end and the existing start is strictly before
        the expanded new end." and "Either failure is rejected with
        `ERR_MECHANIC_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/mechanic_buffered_half_open_overlap
        """
        ctx, req2 = self._setup_one_stop(api, dispatcher_headers)
        # 11:00 start minus 15-minute buffer (10:45) is strictly before the
        # existing stop's 11:00 end: conflict.
        resp = api.create_route_stop(ctx["route_day"]["id"], {
            "service_request_id": req2["id"],
            "planned_start": "2026-05-02T11:00:00Z", "planned_end": "2026-05-02T11:30:00Z",
            "travel_buffer_minutes": 15,
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_MECHANIC_WINDOW_OVERLAP)

    def test_exact_touch_at_buffer_boundary_allowed(self, api, dispatcher_headers):
        """PRD §3.6: "An exact touch at the expanded boundary is allowed: a stop
        beginning precisely at the prior stop's end plus the buffer does not
        conflict."

        Design: Difficulty/resource_temporal_overlap/mechanic_buffered_half_open_overlap
        """
        ctx, req2 = self._setup_one_stop(api, dispatcher_headers)
        # Existing stop ends 11:00; new stop begins exactly at 11:00 + 15 minutes.
        resp = api.create_route_stop(ctx["route_day"]["id"], {
            "service_request_id": req2["id"],
            "planned_start": "2026-05-02T11:15:00Z", "planned_end": "2026-05-02T11:45:00Z",
            "travel_buffer_minutes": 15,
        }, dispatcher_headers)
        stop = validate_success(resp, 201)
        assert stop["seq"] == 2, f"second stop must take seq 2, got {stop['seq']}"
        assert stop["status"] == "PLANNED"


class TestResequence:
    def test_resequence_rewrites_stop_order(self, api, dispatcher_headers):
        """PRD §3.6: "The operation rewrites each stop's `seq` in the given order
        and increments the route day's `version` by one."

        Design: Corner/endpoints/resequence_rewrites_stop_order
        """
        ctx = setup_two_stop_route_day()
        rd_v = ctx["route_day"]["version"]
        resp = validate_success(api.resequence_route_day(ctx["route_day"]["id"], {
            "stop_ids": [ctx["stop2"]["id"], ctx["stop1"]["id"]],
            "expected_route_day_version": rd_v,
        }, dispatcher_headers), 200)
        assert resp["version"] == rd_v + 1, (
            f"resequence must bump route day version to {rd_v + 1}, got {resp['version']}")

        stops2, _ = validate_paginated(api.list_route_stops(
            dispatcher_headers, params={"service_request_id": ctx["req2"]["id"]}))
        stops1, _ = validate_paginated(api.list_route_stops(
            dispatcher_headers, params={"service_request_id": ctx["req1"]["id"]}))
        assert stops2[0]["seq"] == 1, f"stop2 must become seq 1, got {stops2[0]['seq']}"
        assert stops1[0]["seq"] == 2, f"stop1 must become seq 2, got {stops1[0]['seq']}"

    def test_occ_stale_resequence_returns_412(self, api, dispatcher_headers):
        """PRD §2.7: "Rewriting the visit order of a route day requires
        `expected_route_day_version` matching that route day's current `version`;
        if the route day's version has advanced since the client last read it, the
        resequence is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_resequence_returns_412
        """
        ctx = setup_two_stop_route_day()
        rd_v = ctx["route_day"]["version"]
        order = [ctx["stop2"]["id"], ctx["stop1"]["id"]]

        stale = api.resequence_route_day(ctx["route_day"]["id"], {
            "stop_ids": order, "expected_route_day_version": rd_v - 1,
        }, dispatcher_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.resequence_route_day(ctx["route_day"]["id"], {
            "stop_ids": order, "expected_route_day_version": rd_v,
        }, dispatcher_headers), 200)
        assert fresh["version"] == rd_v + 1
