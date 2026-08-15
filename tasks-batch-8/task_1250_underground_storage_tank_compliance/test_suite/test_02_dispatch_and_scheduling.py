"""Service order creation, quoting, dispatch/scheduling rules, edits (OCC),
and cancellation gates (PRD §3.3)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_owner_headers,
    create_service_order_payload,
    create_facility, create_tank, add_component, setup_active_facility_with_tank,
    setup_cp_site, setup_failed_cp_order, create_technician, create_order,
    schedule_order, set_clock, get_order, get_tank,
    MOBILIZATION_FLAT_CENTS,
    api_client,
)

OWNER = TEST_USERS["facility_owner_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
READER = TEST_USERS["any_headers"]

TIGHTNESS_LINES = [{"description": "t", "qty": 1, "unit_price_cents": 60000}]


class TestQuoteComputation:
    def test_quote_per_line_rounding_two_lines(self, api):
        """PRD §3.3: "The quote total is computed in a pinned order: for each line,
        the quantity is multiplied by the unit price and that product is rounded
        half-up to whole cents; the rounded line amounts are then summed; and a
        flat mobilization charge of 15000 cents is added to the sum, yielding
        `quote_total_cents`. Rounding per line first and then summing is mandatory
        — summing exact products and rounding once at the end produces different
        cents and is incorrect."

        Design: Difficulty/combinatorial_formula/quote_per_line_rounding_beats_sum_rounding
        """
        facility = create_facility(facility_name="Quote Site", state_code="OR")
        tank = create_tank(facility["id"])
        # round_half_up(0.5 * 10001) = 5001 per line; 5001 + 5001 + 15000 = 25002.
        # Sum-then-round would give round(10001.0) + 15000 = 25001.
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=[
                                 {"description": "tightness labor", "qty": 0.5,
                                  "unit_price_cents": 10001},
                                 {"description": "report prep", "qty": 0.5,
                                  "unit_price_cents": 10001},
                             ])
        assert order["quote_total_cents"] == 25002

    def test_quote_per_line_rounding_three_lines(self, api):
        """PRD §3.3: "Rounding per line first and then summing is mandatory —
        summing exact products and rounding once at the end produces different
        cents and is incorrect."

        Design: Difficulty/combinatorial_formula/quote_per_line_rounding_beats_sum_rounding
        """
        facility = create_facility(facility_name="Quote Site 3", state_code="OR")
        tank = create_tank(facility["id"])
        # Per line: round_half_up(0.5 * 10001) = 5001; 3 * 5001 + 15000 = 30003.
        # Sum-then-round would give round(15001.5) = 15002 -> 30002.
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=[
                                 {"description": f"line {i}", "qty": 0.5,
                                  "unit_price_cents": 10001}
                                 for i in range(3)
                             ])
        assert order["quote_total_cents"] == 30003


class TestOrderCreation:
    def test_service_order_initial_state_on_create(self, api):
        """PRD §3.3: "A new order enters in `REQUESTED` status with
        `result_outcome` of `NONE`."

        Design: Corner/state_machines/service_order_initial_state_on_create
        """
        facility = create_facility(facility_name="Init Site")
        tank = create_tank(facility["id"])
        order = validate_success(api.create_service_order(
            create_service_order_payload(facility["id"], tank["id"], "TANK_TIGHTNESS"),
            ADMIN), 201)
        assert order["status"] == "REQUESTED"
        assert order["result_outcome"] == "NONE"
        assert isinstance(order["version"], int)

    def test_service_order_retrieval_returns_stored_fields(self, api):
        """PRD §3.3: "The creation payload names the `facility_id`, the
        `tank_system_id` under test, the `service_type`" and "a flat mobilization
        charge of 15000 cents is added to the sum, yielding `quote_total_cents`."
        PRD §3.3: "Dispatchers can sift the order book by `facility_id`,
        `tank_system_id`, `component_id`, `technician_id`, `linked_deficiency_id`,
        `performed_by_technician_id`, `certified_by_technician_id`, and `status`."

        Design: Corner/entities/service_order_retrieval_returns_stored_fields
        """
        facility = create_facility(facility_name="Get Site")
        tank = create_tank(facility["id"])
        order = create_order(facility["id"], tank["id"], "LINE_TIGHTNESS",
                             line_items=[{"description": "line test", "qty": 1,
                                          "unit_price_cents": 50000}])

        got = validate_success(api.get_service_order(order["id"], READER), 200)
        assert got["facility_id"] == facility["id"]
        assert got["tank_system_id"] == tank["id"]
        assert got["service_type"] == "LINE_TIGHTNESS"
        assert got["status"] == "REQUESTED" and got["result_outcome"] == "NONE"
        assert got["quote_total_cents"] == 50000 + MOBILIZATION_FLAT_CENTS == 65000

        data, meta = validate_paginated(
            api.list_service_orders(READER, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == order["id"]

    def test_component_mismatch_rejected(self, api):
        """PRD §3.3: "Component-level service types demand a `component_id`: a
        `CP_SURVEY` order must reference a `CATHODIC_PROTECTION` component, an
        `LLD_FUNCTION` order a `LINE_LEAK_DETECTOR`, and a
        `SPILL_OVERFILL_INSPECTION` a `SPILL_BUCKET` or `OVERFILL_DEVICE`, and in
        every case the component must live on the order's tank; tightness orders
        (`TANK_TIGHTNESS`, `LINE_TIGHTNESS`) must carry no component at all. Any
        violation — a missing component where one is required, a present component
        where none is allowed, a component on the wrong tank, or the wrong
        component type for the service — is rejected with
        `ERR_COMPONENT_MISMATCH`."

        Design: Corner/validations/component_mismatch_rejected
        """
        facility = create_facility(facility_name="Mismatch Site")
        tank = create_tank(facility["id"])
        comp = add_component(tank["id"], "SPILL_BUCKET", serial_no="SB-2")

        res1 = api.create_service_order(
            create_service_order_payload(facility["id"], tank["id"], "CP_SURVEY",
                                         component_id=comp["id"],
                                         line_items=[{"description": "cp", "qty": 1,
                                                      "unit_price_cents": 40000}]),
            ADMIN)
        validate_error(res1, ApiErrorId.ERR_COMPONENT_MISMATCH)

        res2 = api.create_service_order(
            create_service_order_payload(facility["id"], tank["id"], "TANK_TIGHTNESS",
                                         component_id=comp["id"],
                                         line_items=TIGHTNESS_LINES), ADMIN)
        validate_error(res2, ApiErrorId.ERR_COMPONENT_MISMATCH)

    def test_tank_facility_mismatch_rejected(self, api):
        """PRD §3.3: "The tank must belong to the named facility, or the request
        fails with `ERR_TANK_FACILITY_MISMATCH`."

        Design: Corner/errors/tank_facility_mismatch_rejected
        """
        fac1 = create_facility("owner-1", facility_name="F1")
        fac2 = create_facility("owner-2", facility_name="F2")
        tank2 = create_tank(fac2["id"], "owner-2")

        res = api.create_service_order(
            create_service_order_payload(fac1["id"], tank2["id"], "TANK_TIGHTNESS",
                                         line_items=TIGHTNESS_LINES), ADMIN)
        validate_error(res, ApiErrorId.ERR_TANK_FACILITY_MISMATCH)

    def test_deficiency_link_wrong_tank_rejected(self, api):
        """PRD §3.3: "An order may also be marked as the re-test for an existing
        deficiency by supplying `linked_deficiency_id`; that deficiency must belong
        to the same tank and sit in `OPEN`, `CORRECTION_ORDERED`, or `CORRECTED`
        status, failing which the create is rejected with
        `ERR_DEFICIENCY_LINK_INVALID`."

        Design: Corner/validations/deficiency_link_wrong_tank_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_failed_cp_order()  # OPEN MAJOR deficiency on ctx["tank"]
        facility = ctx["facility"]
        tank2 = create_tank(facility["id"], tank_tag="T2")
        place = api.place_in_service(tank2["id"], OWNER)
        assert place.status_code == 200

        res = api.create_service_order(
            create_service_order_payload(
                facility["id"], tank2["id"], "TANK_TIGHTNESS",
                line_items=TIGHTNESS_LINES,
                linked_deficiency_id=ctx["deficiency"]["id"]), ADMIN)
        validate_error(res, ApiErrorId.ERR_DEFICIENCY_LINK_INVALID)


class TestSchedulingGates:
    def test_schedule_window_end_equal_start_invalid(self, api):
        """PRD §3.3: "the window must be valid, meaning `window_end` strictly after
        `window_start` (`ERR_INVALID_WINDOW`)"

        Design: Corner/validations/schedule_window_end_before_start_invalid
        """
        facility, tank = setup_active_facility_with_tank()
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="TT")
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=TIGHTNESS_LINES)
        res = api.schedule_service_order(
            order["id"],
            {"technician_id": t_tt["id"],
             "window_start": "2026-05-02T10:00:00Z",
             "window_end": "2026-05-02T10:00:00Z"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)

    def test_endorsement_missing_on_schedule_rejected(self, api):
        """PRD §3.3: "the named technician must exist, be `active`, and hold the
        endorsement the service type maps to — `TIGHTNESS_TESTER` for
        `TANK_TIGHTNESS` and `LINE_TIGHTNESS`, `LLD_TESTER` for `LLD_FUNCTION`,
        `CP_TESTER` for `CP_SURVEY`, and `INSPECTOR` for
        `SPILL_OVERFILL_INSPECTION` — with a missing endorsement or an inactive
        technician rejected as `ERR_ENDORSEMENT_MISSING`"

        Design: Corner/endpoints/endorsement_missing_on_schedule_rejected
        """
        ctx = setup_cp_site()
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="TT only")
        order = create_order(ctx["facility"]["id"], ctx["tank"]["id"], "CP_SURVEY",
                             component_id=ctx["component"]["id"],
                             line_items=[{"description": "cp", "qty": 1,
                                          "unit_price_cents": 40000}])
        res = api.schedule_service_order(
            order["id"],
            {"technician_id": t_tt["id"],
             "window_start": "2026-05-02T10:00:00Z",
             "window_end": "2026-05-02T11:00:00Z"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_ENDORSEMENT_MISSING)

    def test_schedule_blocked_when_tank_not_in_service(self, api):
        """PRD §3.3: "The checks run in order: the order must be `REQUESTED`
        (`ERR_ORDER_NOT_REQUESTED`); the tank must be `IN_SERVICE`
        (`ERR_TANK_NOT_IN_SERVICE`)"

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_when_tank_not_in_service
        """
        set_clock("2026-05-01T00:00:00Z")
        # Tank stays REGISTERED (never placed in service), so the order remains
        # REQUESTED and the schedule gate reaches the tank check. Closing an
        # IN_SERVICE tank instead would cascade-cancel the order (PRD §3.2) and
        # the earlier ERR_ORDER_NOT_REQUESTED check would fire first (PRD §3.3:
        # "The checks run in order: the order must be REQUESTED ...; the tank
        # must be IN_SERVICE ...").
        facility = create_facility()
        tank = create_tank(facility["id"])
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="TT")
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=TIGHTNESS_LINES)

        res = api.schedule_service_order(
            order["id"],
            {"technician_id": t_tt["id"],
             "window_start": "2026-05-02T10:00:00Z",
             "window_end": "2026-05-02T11:00:00Z"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_TANK_NOT_IN_SERVICE, expected_status=409)

    def test_schedule_unblocked_after_return_to_service(self, api):
        """PRD §3.2: "A clean return moves the tank `TEMPORARILY_CLOSED` →
        `IN_SERVICE`."
        PRD §3.3: "Scheduling converts a request into an assignment. A
        `ContractorAdmin` schedules an order by naming the `technician_id` and the
        half-open service window from `window_start` (inclusive) to `window_end`
        (exclusive)."

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_when_tank_not_in_service
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="TT")
        validate_success(
            api.close_tank(tank["id"], {"closure_type": "TEMPORARY"}, OWNER), 200)
        validate_success(api.return_to_service(tank["id"], OWNER), 200)
        # Create the order after the clean return: closure cancels REQUESTED
        # orders (PRD §3.2), so an order opened before closure would be gone.
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=TIGHTNESS_LINES)

        scheduled = schedule_order(order["id"], t_tt["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["technician_id"] == t_tt["id"]


class TestTechnicianWindowOverlap:
    def _setup_overlap_site(self):
        facility, tank = setup_active_facility_with_tank()
        tank2 = create_tank(facility["id"], tank_tag="T2")
        place = api_client.place_in_service(tank2["id"], OWNER)
        assert place.status_code == 200
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="TT")
        order_a = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                               line_items=TIGHTNESS_LINES)
        schedule_order(order_a["id"], t_tt["id"],
                       "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z")
        return facility, tank, tank2, t_tt, order_a

    def test_adjacent_windows_allowed_half_open(self, api):
        """PRD §3.3: "the technician must have no other `SCHEDULED` or
        `IN_PROGRESS` order whose half-open window intersects the requested one,
        with mere adjacency — one window's end equal to the other's start —
        explicitly allowed (`ERR_TECHNICIAN_DOUBLE_BOOKED`)"

        Design: Difficulty/resource_temporal_overlap/technician_windows_half_open_adjacency
        """
        facility, tank, tank2, t_tt, _ = self._setup_overlap_site()
        order_b = create_order(facility["id"], tank2["id"], "TANK_TIGHTNESS",
                               line_items=TIGHTNESS_LINES)
        # [10:00,12:00) then [12:00,14:00): end == start is adjacency, not overlap.
        scheduled = schedule_order(order_b["id"], t_tt["id"],
                                   "2026-05-10T12:00:00Z", "2026-05-10T14:00:00Z")
        assert scheduled["status"] == "SCHEDULED"

    def test_intersecting_window_rejected(self, api):
        """PRD §3.3: "the technician must have no other `SCHEDULED` or
        `IN_PROGRESS` order whose half-open window intersects the requested one,
        with mere adjacency — one window's end equal to the other's start —
        explicitly allowed (`ERR_TECHNICIAN_DOUBLE_BOOKED`)"

        Design: Difficulty/resource_temporal_overlap/technician_windows_half_open_adjacency
        """
        facility, tank, tank2, t_tt, _ = self._setup_overlap_site()
        order_c = create_order(facility["id"], tank2["id"], "TANK_TIGHTNESS",
                               line_items=TIGHTNESS_LINES)
        # [11:00,13:00) genuinely intersects the existing [10:00,12:00).
        res = api.schedule_service_order(
            order_c["id"],
            {"technician_id": t_tt["id"],
             "window_start": "2026-05-10T11:00:00Z",
             "window_end": "2026-05-10T13:00:00Z"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED, expected_status=409)


class TestTankStabilizationBuffer:
    def _setup_buffer_site(self):
        """One IN_SERVICE tank; three distinct TIGHTNESS_TESTER technicians so the
        double-booking rule cannot confound the buffer assertions."""
        facility, tank = setup_active_facility_with_tank()
        techs = [create_technician(["TIGHTNESS_TESTER"], full_name=f"TT {i}")
                 for i in range(3)]
        order_a = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                               line_items=TIGHTNESS_LINES)
        schedule_order(order_a["id"], techs[0]["id"],
                       "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")
        return facility, tank, techs

    def test_stabilization_exactly_8h_allowed(self, api):
        """PRD §3.3: "the tank must have had no other `TANK_TIGHTNESS` order in
        `SCHEDULED`, `IN_PROGRESS`, or `CERTIFIED` whose window ends less than 8
        hours before the requested `window_start` or starts less than 8 hours after
        the requested `window_end`, a stabilization buffer in which exactly 8 hours
        of separation is permitted (`ERR_TANK_STABILIZATION_WINDOW`)"

        Design: Difficulty/resource_temporal_overlap/tank_tightness_stabilization_buffer_exact
        """
        facility, tank, techs = self._setup_buffer_site()
        order_b = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                               line_items=TIGHTNESS_LINES)
        # Prior window_end 10:00 -> new window_start 18:00 is exactly 8h: allowed.
        scheduled = schedule_order(order_b["id"], techs[1]["id"],
                                   "2026-05-10T18:00:00Z", "2026-05-10T19:00:00Z")
        assert scheduled["status"] == "SCHEDULED"

    def test_stabilization_6h_gap_rejected(self, api):
        """PRD §3.3: "the tank must have had no other `TANK_TIGHTNESS` order in
        `SCHEDULED`, `IN_PROGRESS`, or `CERTIFIED` whose window ends less than 8
        hours before the requested `window_start`" and the rejection carries
        "`ERR_TANK_STABILIZATION_WINDOW`".

        Design: Difficulty/resource_temporal_overlap/tank_tightness_stabilization_buffer_exact
        """
        facility, tank, techs = self._setup_buffer_site()
        order_c = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                               line_items=TIGHTNESS_LINES)
        # Prior window_end 10:00 -> new window_start 16:00 leaves only 6h.
        res = api.schedule_service_order(
            order_c["id"],
            {"technician_id": techs[2]["id"],
             "window_start": "2026-05-10T16:00:00Z",
             "window_end": "2026-05-10T17:00:00Z"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_TANK_STABILIZATION_WINDOW, expected_status=409)


class TestOrderEditAndCancel:
    def test_occ_stale_version_rejected_on_second_order_update(self, api):
        """PRD §2.8: "Editing a service order requires the request to carry
        `expected_service_order_version`, holding the `version` of the order as
        the client last observed it. If the order's current `version` has advanced
        beyond that value — because another dispatcher edited the order in the
        meantime — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), and
        the client must re-read the order before retrying."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_on_second_order_update
        """
        facility = create_facility(facility_name="OCC Site")
        tank = create_tank(facility["id"])
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=TIGHTNESS_LINES)
        stale_v = order["version"]

        updated = validate_success(api.update_service_order(
            order["id"],
            {"expected_service_order_version": stale_v,
             "line_items": [{"description": "t2", "qty": 2, "unit_price_cents": 60000}]},
            ADMIN), 200)
        assert updated["version"] == stale_v + 1
        # 2 * 60000 + 15000 mobilization = 135000 (quote recomputed per line).
        assert updated["quote_total_cents"] == 135000

        res = api.update_service_order(
            order["id"],
            {"expected_service_order_version": stale_v,
             "line_items": [{"description": "t3", "qty": 3, "unit_price_cents": 60000}]},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        final = get_order(order["id"])
        assert final["version"] == stale_v + 1, "rejected write must not mutate"

    def test_cancel_in_progress_order_rejected(self, api):
        """PRD §3.3: "Cancellation is available to a `ContractorAdmin` while the
        order is `REQUESTED` or `SCHEDULED`; any other status yields
        `ERR_ORDER_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_in_progress_order_rejected
        """
        from test_helpers import setup_started_tightness_order
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()  # IN_PROGRESS
        res = api.cancel_service_order(ctx["order"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE, expected_status=409)

    def test_cancel_is_terminal_second_cancel_rejected(self, api):
        """PRD §3.3: "Cancellation is available to a `ContractorAdmin` while the
        order is `REQUESTED` or `SCHEDULED`; any other status yields
        `ERR_ORDER_NOT_CANCELLABLE`. Cancellation moves the order to its terminal
        `CANCELLED` state"

        Design: Corner/state_machines/cancel_is_terminal_second_cancel_rejected
        """
        facility, tank = setup_active_facility_with_tank()
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="TT")
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=TIGHTNESS_LINES)
        schedule_order(order["id"], t_tt["id"],
                       "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")

        first = validate_success(api.cancel_service_order(order["id"], ADMIN), 200)
        assert first["status"] == "CANCELLED"
        res = api.cancel_service_order(order["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE, expected_status=409)

    def test_order_state_transitions_rejected(self, api):
        """PRD §3.3: "the order must be `REQUESTED` (`ERR_ORDER_NOT_REQUESTED`)"
        PRD §3.4: "starting requires the order to be `SCHEDULED`
        (`ERR_ORDER_NOT_SCHEDULED`)" and "attempting to record results on an order
        that is not `IN_PROGRESS` fails with `ERR_ORDER_NOT_IN_PROGRESS`"
        PRD §3.3: "editing an order in any other status is rejected with
        `ERR_ORDER_NOT_EDITABLE`"

        Design: Corner/errors/order_state_transitions_rejected
        """
        from test_helpers import make_technician_headers, start_order
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="TT")
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS",
                             line_items=TIGHTNESS_LINES)

        # start on REQUESTED
        res = api.start_service_order(order["id"], make_technician_headers(t_tt["id"]))
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_SCHEDULED, expected_status=409)

        schedule_order(order["id"], t_tt["id"],
                       "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")

        # second schedule on SCHEDULED
        res = api.schedule_service_order(
            order["id"],
            {"technician_id": t_tt["id"],
             "window_start": "2026-05-03T10:00:00Z",
             "window_end": "2026-05-03T11:00:00Z"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_REQUESTED, expected_status=409)

        # results before start (order still SCHEDULED)
        res = api.record_results(order["id"], {"readings": {"leak_rate_gph": 0.05}},
                                 make_technician_headers(t_tt["id"]))
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_IN_PROGRESS, expected_status=409)

        # start for real, then PUT on IN_PROGRESS
        start_order(order["id"], t_tt["id"], "2026-05-02T10:30:00Z")
        current = get_order(order["id"])
        res = api.update_service_order(
            order["id"],
            {"expected_service_order_version": current["version"],
             "line_items": [{"description": "x", "qty": 1, "unit_price_cents": 1}]},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_EDITABLE, expected_status=409)
