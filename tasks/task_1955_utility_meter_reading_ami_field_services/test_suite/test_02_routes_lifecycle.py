"""Route lifecycle: assignment, state gates, cascades, shift windows.

Covers the route state machine and field-execution gates from PRD sections
2.8 and 3.3.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_route_payload,
    capture_read_payload,
    create_billing_period_payload,
    create_field_technician_payload,
    create_route_payload,
    get_route_stops,
    get_stop,
    make_field_technician_headers,
    mark_stop_no_read_as,
    reassign_route_payload,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_in_progress_route,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_ADMIN = TEST_USERS["meter_ops_admin_headers"]
TEST_BILLING = TEST_USERS["billing_liaison_headers"]


class TestRouteAssignmentStates:
    def test_route_assign_from_assigned_returns_invalid_state(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.3: "A `Dispatcher` assigns a `DRAFT` route by naming
        a `technician_id`"
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/state_machines/route_assign_from_assigned_returns_invalid_state
        """
        tech_a = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Assign A"),
                meter_ops_admin_headers,
            ),
            201,
        )
        tech_b = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Assign B"),
                meter_ops_admin_headers,
            ),
            201,
        )
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(cycle_code="C30"), meter_ops_admin_headers
            ),
            201,
        )
        route = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-03"),
                dispatcher_headers,
            ),
            201,
        )
        validate_success(
            api.assign_route(route["id"], assign_route_payload(tech_a["id"]), dispatcher_headers),
            200,
        )

        res = api.assign_route(
            route["id"], assign_route_payload(tech_b["id"]), dispatcher_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = validate_success(api.get_route(route["id"], dispatcher_headers), 200)
        assert after["route_status"] == "ASSIGNED"
        assert after["technician_id"] == tech_a["id"]

    def test_route_unassign_returns_to_draft_for_reassignment(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.3: "Unassigning returns an `ASSIGNED` route to
        `DRAFT` with `technician_id` cleared to null."

        Design: Corner/state_machines/route_unassign_returns_to_draft_for_reassignment
        """
        tech_a = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Unassign A"),
                meter_ops_admin_headers,
            ),
            201,
        )
        tech_b = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Unassign B"),
                meter_ops_admin_headers,
            ),
            201,
        )
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(cycle_code="C33"), meter_ops_admin_headers
            ),
            201,
        )
        route = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-03"),
                dispatcher_headers,
            ),
            201,
        )
        validate_success(
            api.assign_route(route["id"], assign_route_payload(tech_a["id"]), dispatcher_headers),
            200,
        )

        unassigned = validate_success(api.unassign_route(route["id"], dispatcher_headers), 200)
        assert unassigned["route_status"] == "DRAFT"
        assert unassigned["technician_id"] is None

        reassigned = validate_success(
            api.assign_route(route["id"], assign_route_payload(tech_b["id"]), dispatcher_headers),
            200,
        )
        assert reassigned["route_status"] == "ASSIGNED"
        assert reassigned["technician_id"] == tech_b["id"]

    def test_reassign_from_in_progress_rejected(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.3: "Reassignment from any state other than `ASSIGNED`
        fails with `ERR_ROUTE_NOT_REASSIGNABLE` (HTTP 409)."

        Design: Corner/validations/reassign_from_in_progress_rejected
        """
        tech_a = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Reassign A"),
                meter_ops_admin_headers,
            ),
            201,
        )
        tech_b = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Reassign B"),
                meter_ops_admin_headers,
            ),
            201,
        )
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(cycle_code="C86"), meter_ops_admin_headers
            ),
            201,
        )
        route = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-03"),
                dispatcher_headers,
            ),
            201,
        )
        validate_success(
            api.assign_route(route["id"], assign_route_payload(tech_a["id"]), dispatcher_headers),
            200,
        )
        validate_success(
            api.start_route(route["id"], make_field_technician_headers(tech_a["id"])), 200
        )
        current = validate_success(api.get_route(route["id"], dispatcher_headers), 200)
        assert current["route_status"] == "IN_PROGRESS"

        res = api.reassign_route(
            route["id"],
            reassign_route_payload(tech_b["id"], current["version"]),
            dispatcher_headers,
        )
        validate_error(res, ApiErrorId.ERR_ROUTE_NOT_REASSIGNABLE.value, 409)

        after = validate_success(api.get_route(route["id"], dispatcher_headers), 200)
        assert after["technician_id"] == tech_a["id"]


class TestRouteCancelAndTerminal:
    def test_route_cancel_cascades_pending_stops_to_cancelled(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.3: "Cancelling is possible from `DRAFT` or
        `ASSIGNED`; the route becomes `CANCELLED` and only its stops still in
        `PENDING` cascade to `CANCELLED` — stops in any other state are
        untouched."

        Design: Corner/state_machines/route_cancel_cascades_pending_stops_to_cancelled
        """
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Cancel Tech"),
                meter_ops_admin_headers,
            ),
            201,
        )
        account, meter = setup_account_with_installed_meter("C-0031", "C31")
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(cycle_code="C31"), meter_ops_admin_headers
            ),
            201,
        )
        route = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-03"),
                dispatcher_headers,
            ),
            201,
        )
        stops = get_route_stops(route["id"])
        assert len(stops) == 1
        validate_success(
            api.assign_route(route["id"], assign_route_payload(tech["id"]), dispatcher_headers),
            200,
        )

        cancelled = validate_success(api.cancel_route(route["id"], dispatcher_headers), 200)
        assert cancelled["route_status"] == "CANCELLED"

        stop_after = validate_success(api.get_route_stop(stops[0]["id"], dispatcher_headers), 200)
        assert stop_after["stop_status"] == "CANCELLED"

    def test_route_terminal_lockdown_reconciled_rejects_cancel_and_assign(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.3: "After completion, a `Dispatcher` reconciles the
        route, moving it to the terminal `RECONCILED` state and computing both
        read rates per §2.11"
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/state_machines/route_terminal_lockdown_reconciled_rejects_cancel_and_assign
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter("C-0032", "C32")
        period, route, stops, tech = setup_in_progress_route(
            "C32",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Lock Tech",
        )
        assert len(stops) == 1
        stop = stops[0]
        read = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 500, "2026-08-03T09:00:00Z", stop["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        validate_success(api.validate_read(read["id"], TEST_BILLING), 200)
        validate_success(
            api.complete_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        reconciled = validate_success(api.reconcile_route(route["id"], dispatcher_headers), 200)
        assert reconciled["route_status"] == "RECONCILED"

        res_cancel = api.cancel_route(route["id"], dispatcher_headers)
        validate_error(res_cancel, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        res_assign = api.assign_route(
            route["id"], assign_route_payload(tech["id"]), dispatcher_headers
        )
        validate_error(res_assign, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = validate_success(api.get_route(route["id"], dispatcher_headers), 200)
        assert after["route_status"] == "RECONCILED"


class TestRouteCompletionGate:
    def test_route_complete_with_pending_stops_rejected(self, api, dispatcher_headers):
        """PRD section 3.3: "Completion moves an `IN_PROGRESS` route to
        `COMPLETED`, again restricted to the assigned technician, and is gated
        on field work being settled — any stop still in `PENDING` blocks
        completion with `ERR_ROUTE_HAS_PENDING_STOPS` (HTTP 409), though stops
        in `NO_READ_PENDING` or `SKIPPED_HAZARD` do not."

        Design: Corner/validations/route_complete_with_pending_stops_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter("C-0087", "C87")
        period, route, stops, tech = setup_in_progress_route(
            "C87",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Pend Tech",
        )
        assert len(stops) == 1
        stop = stops[0]

        res = api.complete_route(route["id"], make_field_technician_headers(tech["id"]))
        validate_error(res, ApiErrorId.ERR_ROUTE_HAS_PENDING_STOPS.value, 409)

        mark_stop_no_read_as(stop["id"], tech["id"])
        completed = validate_success(
            api.complete_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        assert completed["route_status"] == "COMPLETED"


class TestRouteWindowAndFilters:
    def test_route_scheduled_date_window_boundaries(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 2.8: "The read window is the interval from
        `read_window_open_date` through `read_window_close_date` with both
        endpoints inclusive."
        PRD section 2.8: "a route whose `scheduled_date` falls outside its
        period's window is rejected with `ERR_ROUTE_OUTSIDE_READ_WINDOW` (HTTP
        422)."

        Design: Corner/calculations/route_scheduled_date_window_boundaries
        """
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(
                    cycle_code="C60",
                    period_start_date="2026-08-01",
                    period_end_date="2026-08-31",
                    read_window_open_date="2026-08-10",
                    read_window_close_date="2026-08-14",
                    bill_run_date="2026-08-31",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )

        ok = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-14"),
                dispatcher_headers,
            ),
            201,
        )
        assert ok["scheduled_date"] == "2026-08-14"

        res = api.create_route(
            create_route_payload(period["id"], scheduled_date="2026-08-15"),
            dispatcher_headers,
        )
        validate_error(res, ApiErrorId.ERR_ROUTE_OUTSIDE_READ_WINDOW.value, 422)

    def test_route_stop_filtered_list_by_status(self, api, dispatcher_headers):
        """PRD section 3.2: "the stop collection itself filters by `route_id`,
        `service_account_id`, `billing_cycle_period_id`, `stop_status`,
        `hazard_flag_id`, or `current_read_id`."

        Design: Corner/endpoints/route_stop_filtered_list_by_status
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter("C-0111", "CC2")
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(cycle_code="CC2"),
                TEST_ADMIN,
            ),
            201,
        )
        set_logical_clock("2026-08-03T08:00:00Z")
        validate_success(api.open_read_window(period["id"], TEST_BILLING), 200)
        route_a = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-03"),
                dispatcher_headers,
            ),
            201,
        )
        route_b = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-04"),
                dispatcher_headers,
            ),
            201,
        )
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Stop Filter Tech"), TEST_ADMIN
            ),
            201,
        )
        validate_success(
            api.assign_route(route_a["id"], assign_route_payload(tech["id"]), dispatcher_headers),
            200,
        )
        validate_success(
            api.start_route(route_a["id"], make_field_technician_headers(tech["id"])), 200
        )
        stops_a = get_route_stops(route_a["id"])
        assert len(stops_a) == 1
        mark_stop_no_read_as(stops_a[0]["id"], tech["id"])
        stops_b = get_route_stops(route_b["id"])
        assert len(stops_b) == 1

        data, meta = validate_paginated(
            api.list_stops(dispatcher_headers, params={"stop_status": "NO_READ_PENDING"})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == stops_a[0]["id"]

        data, meta = validate_paginated(
            api.list_stops(dispatcher_headers, params={"stop_status": "PENDING"})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == stops_b[0]["id"]
        assert data[0]["id"] != stops_a[0]["id"]


class TestTechnicianShiftWindows:
    """Half-open shift intervals on the technician resource (PRD 2.8)."""

    def _three_routes_same_day(self, api, meter_ops_admin_headers, dispatcher_headers):
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Tech Ten"),
                meter_ops_admin_headers,
            ),
            201,
        )
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(
                    cycle_code="C19",
                    period_start_date="2026-08-01",
                    period_end_date="2026-08-31",
                    read_window_open_date="2026-08-10",
                    read_window_close_date="2026-08-14",
                    bill_run_date="2026-08-31",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        route_a = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-10", route_shift="AM"),
                dispatcher_headers,
            ),
            201,
        )
        route_b = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-10", route_shift="AM"),
                dispatcher_headers,
            ),
            201,
        )
        route_c = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-10", route_shift="PM"),
                dispatcher_headers,
            ),
            201,
        )
        return tech, route_a, route_b, route_c

    def test_overlapping_am_shifts_rejected(self, api, meter_ops_admin_headers, dispatcher_headers):
        """PRD section 2.8: "One technician cannot hold two commitments on the
        same date whose shift intervals overlap — an `AM` commitment and a `PM`
        commitment on the same date are adjacent, not overlapping, and are
        allowed. Violations surface as `ERR_TECHNICIAN_WINDOW_CONFLICT` (HTTP
        409) at route assignment and reassignment and at work-order dispatch
        and reschedule."

        Design: Difficulty/resource_temporal_overlap/technician_shift_windows_reject_overlap_allow_adjacency
        """
        tech, route_a, route_b, _route_c = self._three_routes_same_day(
            api, meter_ops_admin_headers, dispatcher_headers
        )
        validate_success(
            api.assign_route(route_a["id"], assign_route_payload(tech["id"]), dispatcher_headers),
            200,
        )

        res = api.assign_route(
            route_b["id"], assign_route_payload(tech["id"]), dispatcher_headers
        )
        validate_error(res, ApiErrorId.ERR_TECHNICIAN_WINDOW_CONFLICT.value, 409)

        after_b = validate_success(api.get_route(route_b["id"], dispatcher_headers), 200)
        assert after_b["route_status"] == "DRAFT"
        after_a = validate_success(api.get_route(route_a["id"], dispatcher_headers), 200)
        assert after_a["route_status"] == "ASSIGNED"

    def test_am_then_pm_adjacency_allowed(self, api, meter_ops_admin_headers, dispatcher_headers):
        """PRD section 2.8: "The `AM` shift runs from 06:00 up to but not
        including 12:00; the `PM` shift runs from 12:00 up to but not
        including 18:00; the `FULL` shift runs from 06:00 up to but not
        including 18:00."
        PRD section 2.8: "an `AM` commitment and a `PM` commitment on the same
        date are adjacent, not overlapping, and are allowed."

        Design: Difficulty/resource_temporal_overlap/technician_shift_windows_reject_overlap_allow_adjacency
        """
        tech, route_a, _route_b, route_c = self._three_routes_same_day(
            api, meter_ops_admin_headers, dispatcher_headers
        )
        validate_success(
            api.assign_route(route_a["id"], assign_route_payload(tech["id"]), dispatcher_headers),
            200,
        )
        assigned_c = validate_success(
            api.assign_route(route_c["id"], assign_route_payload(tech["id"]), dispatcher_headers),
            200,
        )
        assert assigned_c["route_status"] == "ASSIGNED"
        assert assigned_c["technician_id"] == tech["id"]


class TestStopCaptureRouteGate:
    """Stop capture requires the route IN_PROGRESS (PRD 3.3)."""

    def _assigned_route_with_stop(self, api, meter_ops_admin_headers, dispatcher_headers):
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter("A-9001", "C17")
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(cycle_code="C17"), meter_ops_admin_headers
            ),
            201,
        )
        set_logical_clock("2026-08-03T08:00:00Z")
        validate_success(api.open_read_window(period["id"], TEST_BILLING), 200)
        route = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-03"),
                dispatcher_headers,
            ),
            201,
        )
        stops = get_route_stops(route["id"])
        assert len(stops) == 1
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Tech Nine"), meter_ops_admin_headers
            ),
            201,
        )
        route = validate_success(
            api.assign_route(route["id"], assign_route_payload(tech["id"]), dispatcher_headers),
            200,
        )
        return account, meter, route, stops[0], tech

    def test_capture_rejected_while_route_assigned(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.3: "The request is then checked, in the §2.6 order,
        against the route being `IN_PROGRESS` (`ERR_ROUTE_NOT_IN_PROGRESS`),
        the period being `WINDOW_OPEN` (`ERR_READ_WINDOW_NOT_OPEN`), the hazard
        screen — an `ACTIVE` hazard flag on the account blocks capture unless
        the route's `two_person_crew` is true (`ERR_ACTIVE_HAZARD_BLOCKS_READ`,
        HTTP 422) — the `read_at` date falling inside the read window on both
        ends (`ERR_READ_OUTSIDE_WINDOW`), the presented `meter_id` being the
        account's currently installed meter (`ERR_METER_NOT_INSTALLED_AT_ACCOUNT`,
        HTTP 409), and the rollback rule against `last_validated_read_value`
        (`ERR_READ_ROLLBACK`)."

        Design: Difficulty/cross_entity_state_dependency/stop_capture_gated_by_route_in_progress
        """
        _account, meter, route, stop, tech = self._assigned_route_with_stop(
            api, meter_ops_admin_headers, dispatcher_headers
        )
        assert route["route_status"] == "ASSIGNED"

        res = api.capture_read(
            stop["id"],
            capture_read_payload(meter["id"], 700, "2026-08-03T09:00:00Z", stop["version"]),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ROUTE_NOT_IN_PROGRESS.value, 409)

        after = get_stop(stop["id"])
        assert after["stop_status"] == "PENDING"

    def test_capture_succeeds_once_route_in_progress(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.3: "Field work starts when the assigned technician
        starts the route: the caller's `X-User-ID` must equal the route's
        `technician_id` (`ERR_NOT_ASSIGNED_TECHNICIAN`, HTTP 403), and the
        route moves from `ASSIGNED` to `IN_PROGRESS`."
        PRD section 3.3: "A successful capture creates a MeterRead with
        `read_source` `HANDHELD` and `read_status` `PROVISIONAL`, moves the
        stop to `READ_CAPTURED`, points the stop's `current_read_id` at the new
        read, and increments the stop's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/stop_capture_gated_by_route_in_progress
        """
        _account, meter, route, stop, tech = self._assigned_route_with_stop(
            api, meter_ops_admin_headers, dispatcher_headers
        )
        validate_success(
            api.start_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        read = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 700, "2026-08-03T09:00:00Z", stop["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert read["read_status"] == "PROVISIONAL"
        assert read["read_source"] == "HANDHELD"

        after = get_stop(stop["id"])
        assert after["stop_status"] == "READ_CAPTURED"
        assert after["current_read_id"] == read["id"]
