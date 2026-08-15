"""Service dispatch: van-stock conservation, buffered windows, technician
lifecycle gates, release/re-dispatch, PM resolution, and RBAC."""
from test_helpers import (
    ApiErrorId,
    get_service_call,
    get_technician,
    get_unit,
    make_customer,
    make_dispatched_call,
    make_service_call,
    make_technician,
    make_technician_headers,
    make_unit,
    resolve_call,
    validate_error,
    validate_success,
    van_stock_qty,
)


class TestVanStockConservation:
    def _dispatched_parts_scenario(self, api):
        """Technician with van_stock [{P-100, 5}]; OPEN call requiring
        [{P-100, 2}] dispatched to them."""
        customer = make_customer(name="Parts Co")
        unit = make_unit(serial_number="SN-CI2")
        tech = make_technician(full_name="Tech Van",
                               van_stock=[{"part_number": "P-100", "qty": 5}])
        call = make_dispatched_call(
            unit["id"], customer["id"], tech["id"],
            required_parts=[{"part_number": "P-100", "qty": 2}])
        return customer, unit, tech, call

    def test_dispatch_decrements_van_stock(self, api):
        """PRD §3.5: "A successful dispatch records `technician_id`,
        `scheduled_start`, and `scheduled_end` on the call, decrements the
        technician's `van_stock` by the required quantities (the parts are
        loaded onto the job)".

        Design: Difficulty/compensating_invariant/dispatch_release_van_stock_invariant
        """
        _customer, _unit, tech, call = self._dispatched_parts_scenario(api)
        assert call["status"] == "DISPATCHED"
        assert call["technician_id"] == tech["id"]
        assert van_stock_qty(get_technician(tech["id"]), "P-100") == 3, \
            "5 - 2 loaded onto the job"

    def test_release_restores_van_stock_exactly(self, api,
                                                service_dispatcher_headers):
        """PRD §3.5: "Release backs a dispatched call out, returning it from
        `DISPATCHED` to `OPEN`: the required parts go back onto the van,
        `technician_id`, `scheduled_start`, and `scheduled_end` are cleared to
        null, and if this call had moved the unit to `IN_SHOP` the unit
        returns to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/dispatch_release_van_stock_invariant
        """
        _customer, unit, tech, call = self._dispatched_parts_scenario(api)
        assert get_unit(unit["id"])["availability_status"] == "IN_SHOP"
        released = validate_success(api.release_service_call(
            call["id"], service_dispatcher_headers))
        assert released["status"] == "OPEN"
        assert released["technician_id"] is None
        assert released["scheduled_start"] is None
        assert released["scheduled_end"] is None
        assert van_stock_qty(get_technician(tech["id"]), "P-100") == 5, \
            "exact restoration, no part created or destroyed"
        assert get_unit(unit["id"])["availability_status"] == "AVAILABLE"


class TestDispatchWindowBuffer:
    def _setup_with_first_dispatch(self, api):
        customer = make_customer(name="Dispatch Co")
        unit = make_unit(serial_number="SN-TO2")
        tech = make_technician(full_name="Tech Buf")
        first = make_dispatched_call(
            unit["id"], customer["id"], tech["id"],
            scheduled_start="2026-08-02T10:00:00Z",
            scheduled_end="2026-08-02T11:00:00Z")
        second = make_service_call(unit["id"], customer["id"], call_type="PM")
        return customer, unit, tech, first, second

    def test_dispatch_inside_buffer_rejected(self, api,
                                             service_dispatcher_headers):
        """PRD §3.5: "the dispatch window, expanded by 60 minutes on both
        sides and treated as a closed interval, must not intersect any other
        `DISPATCHED` call's identically expanded closed interval for the same
        technician, else `ERR_DISPATCH_WINDOW_OVERLAP`". The first call's
        buffered interval is [09:00, 12:00]; a 12:00 start (buffered
        [11:00, 14:00]) touches it.

        Design: Difficulty/resource_temporal_overlap/dispatch_window_buffered
        """
        _c, _u, tech, _first, second = self._setup_with_first_dispatch(api)
        resp = api.dispatch_service_call(
            second["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-08-02T12:00:00Z",
             "scheduled_end": "2026-08-02T13:00:00Z"},
            service_dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_WINDOW_OVERLAP, 409)
        assert get_service_call(second["id"])["status"] == "OPEN"

    def test_dispatch_beyond_buffer_succeeds(self, api,
                                             service_dispatcher_headers):
        """PRD §3.5: the buffered closed-interval rule above; a 13:01 start
        expands to [12:01, 15:00], which is disjoint from the first call's
        [09:00, 12:00], so the dispatch succeeds and the call moves
        OPEN -> DISPATCHED.

        Design: Difficulty/resource_temporal_overlap/dispatch_window_buffered
        """
        _c, _u, tech, _first, second = self._setup_with_first_dispatch(api)
        validate_error(api.dispatch_service_call(
            second["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-08-02T12:00:00Z",
             "scheduled_end": "2026-08-02T13:00:00Z"},
            service_dispatcher_headers),
            ApiErrorId.ERR_DISPATCH_WINDOW_OVERLAP, 409)
        data = validate_success(api.dispatch_service_call(
            second["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-08-02T13:01:00Z",
             "scheduled_end": "2026-08-02T14:00:00Z"},
            service_dispatcher_headers))
        assert data["status"] == "DISPATCHED"
        assert data["technician_id"] == tech["id"]


class TestTechnicianLifecycleGate:
    def test_dispatch_to_inactive_technician_rejected(
            self, api, service_dispatcher_headers):
        """PRD §3.5: "the named technician's `status` must be `ACTIVE`, else
        `ERR_TECHNICIAN_INACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_active_technician
        """
        customer = make_customer(name="Tech Co")
        unit = make_unit(serial_number="SN-CE2")
        tech = make_technician(full_name="Tech Idle")
        call = make_service_call(unit["id"], customer["id"],
                                 priority="EMERGENCY")
        validate_success(api.deactivate_technician(tech["id"],
                                                   service_dispatcher_headers))
        resp = api.dispatch_service_call(
            call["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_end": "2026-08-02T11:00:00Z"},
            service_dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_INACTIVE, 422)

    def test_failed_dispatch_leaves_call_open_and_technician_inactive(
            self, api, service_dispatcher_headers):
        """PRD §3.5: dispatch moves a call "from `OPEN` to `DISPATCHED`" only
        on success; PRD §3.5: "Deactivation moves a technician from `ACTIVE`
        to `INACTIVE`, which bars them from new dispatches." After the barred
        dispatch the call stays OPEN and the technician stays INACTIVE.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_active_technician
        """
        customer = make_customer(name="Tech Co")
        unit = make_unit(serial_number="SN-CE2B")
        tech = make_technician(full_name="Tech Idle")
        call = make_service_call(unit["id"], customer["id"],
                                 priority="EMERGENCY")
        validate_success(api.deactivate_technician(tech["id"],
                                                   service_dispatcher_headers))
        validate_error(api.dispatch_service_call(
            call["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_end": "2026-08-02T11:00:00Z"},
            service_dispatcher_headers),
            ApiErrorId.ERR_TECHNICIAN_INACTIVE, 422)
        assert get_service_call(call["id"])["status"] == "OPEN"
        assert get_technician(tech["id"])["status"] == "INACTIVE"


class TestVanStockSufficiency:
    def test_van_stock_insufficient_rejected(self, api,
                                             service_dispatcher_headers):
        """PRD §3.5: "the technician's `van_stock` must cover every required
        part — for each `part_number` and `qty` in `required_parts`, the van's
        entry must hold at least that quantity — else
        `ERR_VAN_STOCK_INSUFFICIENT`". No partial hold is taken on failure.

        Design: Corner/validations/van_stock_insufficient_rejected
        """
        customer = make_customer(name="Parts Short")
        unit = make_unit(serial_number="SN-V4")
        tech = make_technician(full_name="Tech Short",
                               van_stock=[{"part_number": "P-100", "qty": 5}])
        call = make_service_call(
            unit["id"], customer["id"],
            required_parts=[{"part_number": "P-100", "qty": 99}])
        resp = api.dispatch_service_call(
            call["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_end": "2026-08-02T11:00:00Z"},
            service_dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_VAN_STOCK_INSUFFICIENT, 422)
        assert van_stock_qty(get_technician(tech["id"]), "P-100") == 5
        assert get_service_call(call["id"])["status"] == "OPEN"


class TestReleaseRedispatchCycle:
    def test_release_then_redispatch_to_other_technician(
            self, api, service_dispatcher_headers):
        """PRD §3.5: "Release backs a dispatched call out, returning it from
        `DISPATCHED` to `OPEN`" and "The release-and-redispatch loop may
        repeat as often as scheduling demands." Release frees the first
        technician's buffered window, so the same call can be dispatched to a
        different technician at a window overlapping the old one.

        Design: Corner/state_machines/servicecall_release_redispatch_cycle
        """
        customer = make_customer(name="Cycle SC")
        unit = make_unit(serial_number="SN-SC1")
        tech1 = make_technician(full_name="T One")
        tech2 = make_technician(full_name="T Two")
        call = make_dispatched_call(unit["id"], customer["id"], tech1["id"])
        validate_success(api.release_service_call(call["id"],
                                                  service_dispatcher_headers))
        data = validate_success(api.dispatch_service_call(
            call["id"],
            {"technician_id": tech2["id"],
             "scheduled_start": "2026-08-02T10:30:00Z",
             "scheduled_end": "2026-08-02T11:30:00Z"},
            service_dispatcher_headers))
        assert data["status"] == "DISPATCHED"
        assert data["technician_id"] == tech2["id"]


class TestPmResolution:
    def test_pm_resolve_resets_interval(self, api, fleet_manager_headers):
        """PRD §3.5: "When the resolved call is a PM call, one more cascade
        runs: the unit's `last_pm_hours` is set to its current `hour_meter`,
        the `maintenance_posture` clears from `PM_DUE` to `PM_OK`, and
        `next_pm_due_hours` is recomputed as the new `last_pm_hours` plus
        `pm_interval_hours`." Also: "the dispatched-but-unused remainder of
        each part returns to the technician's `van_stock`" and the call "moves
        from `DISPATCHED` to `CLOSED`".

        Design: Corner/calculations/pm_resolve_resets_interval
        """
        customer = make_customer(name="PM Co")
        unit = make_unit(serial_number="SN-PM1")
        tech = make_technician(full_name="Tech PM",
                               van_stock=[{"part_number": "P-OIL", "qty": 4}])
        validate_success(api.create_meter_reading(unit["id"],
                                                  {"reading_hours": 500},
                                                  fleet_manager_headers), 201)
        assert get_unit(unit["id"])["maintenance_posture"] == "PM_DUE"
        call = make_dispatched_call(
            unit["id"], customer["id"], tech["id"],
            scheduled_start="2026-08-02T09:00:00Z",
            scheduled_end="2026-08-02T10:00:00Z", call_type="PM",
            required_parts=[{"part_number": "P-OIL", "qty": 1}])
        closed = resolve_call(call["id"], tech["id"],
                              used_parts=[{"part_number": "P-OIL", "qty": 1}])
        assert closed["status"] == "CLOSED"
        unit_after = get_unit(unit["id"])
        assert unit_after["maintenance_posture"] == "PM_OK"
        assert unit_after["last_pm_hours"] == 500
        assert unit_after["next_pm_due_hours"] == 1000
        assert van_stock_qty(get_technician(tech["id"]), "P-OIL") == 3, \
            "4 - 1 consumed; no unused remainder to return"


class TestTechnicianRestock:
    def test_van_stock_restock_adds_qty(self, api, service_dispatcher_headers):
        """PRD §3.5: "Restocking adds a `qty` to the van's count for a
        `part_number`, creating the entry when the van does not yet carry that
        part."

        Design: Corner/endpoints/van_stock_restock_adds_qty
        """
        tech = make_technician(full_name="Tech Stock",
                               van_stock=[{"part_number": "P-100", "qty": 5}])
        validate_success(api.restock_van(tech["id"],
                                         {"part_number": "P-100", "qty": 3},
                                         service_dispatcher_headers))
        validate_success(api.restock_van(tech["id"],
                                         {"part_number": "P-200", "qty": 2},
                                         service_dispatcher_headers))
        data = get_technician(tech["id"])
        assert van_stock_qty(data, "P-100") == 8
        assert van_stock_qty(data, "P-200") == 2


class TestServiceRbac:
    def test_salesrep_cannot_dispatch_returns_forbidden(
            self, api, sales_rep_headers):
        """PRD §4: POST /fleet/service-calls/{id}/dispatch is authorized for
        ServiceDispatcher only; PRD §2.1: "A request whose role is not
        permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/salesrep_cannot_dispatch_returns_forbidden
        """
        customer = make_customer(name="RBAC Co")
        unit = make_unit(serial_number="SN-RB1")
        tech = make_technician(full_name="Tech RB")
        call = make_service_call(unit["id"], customer["id"])
        resp = api.dispatch_service_call(
            call["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_end": "2026-08-02T11:00:00Z"},
            sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_service_call(call["id"])["status"] == "OPEN"

    def test_technician_cannot_resolve_others_call(self, api):
        """PRD §2.1: "resolving a dispatched service call is permitted only
        when the call's `technician_id` equals the caller's `X-User-ID`; any
        other technician attempting the resolve is rejected with
        `ERR_UNAUTHORIZED`." PRD §3.5: the assigned technician's resolve moves
        the call "from `DISPATCHED` to `CLOSED`".

        Design: Corner/rbac/technician_cannot_resolve_others_call
        """
        customer = make_customer(name="Own Co")
        unit = make_unit(serial_number="SN-RB2")
        tech1 = make_technician(full_name="T Assigned")
        tech2 = make_technician(full_name="T Other")
        call = make_dispatched_call(unit["id"], customer["id"], tech1["id"])
        resp = api.resolve_service_call(call["id"], {"used_parts": []},
                                        make_technician_headers(tech2["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        closed = resolve_call(call["id"], tech1["id"], used_parts=[])
        assert closed["status"] == "CLOSED"
