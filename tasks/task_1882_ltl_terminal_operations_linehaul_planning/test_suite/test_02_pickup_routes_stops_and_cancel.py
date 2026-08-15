"""Pickup routes and stops: shift-window containment, stop transitions, and the
shipment-cancel cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    add_stop,
    create_pickup_stop_payload,
    get_success_data,
    make_on_dock_shipment,
    make_route,
    make_shipment,
    make_terminal_pair,
    make_trailer,
    validate_error,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]


class TestShiftWindow:
    def test_stop_at_shift_boundaries_accepted(self, api):
        """PRD §3.3: "That planned arrival must fall within the route's shift
        window, with both endpoints of the window included — a planned arrival
        exactly at `shift_start_minute` or exactly at `shift_end_minute` is
        acceptable; anything outside is rejected with `ERR_STOP_OUTSIDE_SHIFT`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/pickup_stop_shift_window_closed_interval
        """
        origin, dest = make_terminal_pair()
        s_a = make_shipment(origin["id"], dest["id"], actual_weight_lbs=500)
        s_b = make_shipment(origin["id"], dest["id"], actual_weight_lbs=600)
        route = make_route(origin["id"])  # shift [480, 1020]
        stop_a = add_stop(route["id"], s_a["id"], stop_sequence=1,
                          planned_arrival_minute=480)
        assert stop_a["status"] == "PLANNED", "stop exactly at shift_start is legal"
        stop_b = add_stop(route["id"], s_b["id"], stop_sequence=2,
                          planned_arrival_minute=1020)
        assert stop_b["status"] == "PLANNED", "stop exactly at shift_end is legal"

    @pytest.mark.parametrize("bad_minute", [479, 1021])
    def test_stop_outside_shift_rejected(self, api, bad_minute):
        """PRD §3.3: "That planned arrival must fall within the route's shift
        window, with both endpoints of the window included — a planned arrival
        exactly at `shift_start_minute` or exactly at `shift_end_minute` is
        acceptable; anything outside is rejected with `ERR_STOP_OUTSIDE_SHIFT`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/pickup_stop_shift_window_closed_interval
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], actual_weight_lbs=700)
        route = make_route(origin["id"])  # shift [480, 1020]
        resp = api.create_pickup_stop(
            create_pickup_stop_payload(route["id"], shipment["id"], stop_sequence=3,
                                       planned_arrival_minute=bad_minute),
            headers=DISP,
        )
        validate_error(resp, ApiErrorId.ERR_STOP_OUTSIDE_SHIFT)


class TestStopTransitions:
    def test_arrive_requires_dispatched_route(self, api):
        """PRD §3.3: "marking a stop arrived (`PLANNED` → `ARRIVED`) is only legal
        while the route is `DISPATCHED` — attempting it otherwise is rejected
        with `ERR_ROUTE_NOT_DISPATCHED`"

        Design: Corner/validations/error_route_not_dispatched_on_stop_arrive
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], actual_weight_lbs=500)
        route = make_route(origin["id"])
        stop = add_stop(route["id"], shipment["id"])
        # Route is still PLANNED (never dispatched).
        resp = api.arrive_stop(stop["id"], headers=DISP)
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED)

    def test_complete_twice_rejected(self, api):
        """PRD §3.3: "completing a stop (`ARRIVED` → `PICKED_UP`) is the moment
        the freight physically changes custody: the shipment's `handling_status`
        moves from `TENDERED` to `ON_DOCK`."
        PRD §2.8: "5. Entity state preconditions for the requested transition
        (e.g. trailer must be `LOADING` to accept a manifest entry, a stop must
        be `ARRIVED` to complete, a leg must be `EN_ROUTE` to arrive) →
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/idempotent_duplicate_complete_rejected
        """
        origin, dest = make_terminal_pair()
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=500)
        stop = ctx["stop"]
        assert stop["status"] == "PICKED_UP"
        resp = api.complete_stop(stop["id"], headers=DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        shipment = get_success_data(api.get_shipment(ctx["shipment"]["id"],
                                                     headers=DISP))
        assert shipment["handling_status"] == "ON_DOCK", (
            "a rejected duplicate complete must not double-fire the custody move"
        )


class TestShipmentCancelCascade:
    def test_cancel_cascades_stop_skip_and_route_completion(self, api):
        """PRD §3.1: "A dispatcher may cancel a shipment while it is `TENDERED` or
        `ON_DOCK`, provided no `ACTIVE` manifest entry references it;
        cancellation moves `handling_status` to `CANCELLED` and flips every
        still-`PLANNED` pickup stop referencing the shipment to `SKIPPED`."
        PRD §3.3: "Routes complete themselves by exhaustion: the moment every
        stop on a dispatched route sits in `PICKED_UP` or `SKIPPED`, the route's
        `status` becomes `COMPLETED` without any explicit call."

        Design: Difficulty/transitive_cascade/shipment_cancel_stop_skip_cascade_depth2
        """
        origin, dest = make_terminal_pair()
        s_a = make_shipment(origin["id"], dest["id"], actual_weight_lbs=500)
        s_b = make_shipment(origin["id"], dest["id"], actual_weight_lbs=700)
        route = make_route(origin["id"])
        stop_a = add_stop(route["id"], s_a["id"], stop_sequence=1,
                          planned_arrival_minute=540)
        stop_b = add_stop(route["id"], s_b["id"], stop_sequence=2,
                          planned_arrival_minute=560)
        validate_success(api.dispatch_route(route["id"], headers=DISP))
        validate_success(api.arrive_stop(stop_a["id"], headers=DISP))
        validate_success(api.complete_stop(stop_a["id"], headers=DISP))

        cancelled = validate_success(api.cancel_shipment(s_b["id"], headers=DISP))
        assert cancelled["handling_status"] == "CANCELLED"

        stop_b_after = get_success_data(api.get_pickup_stop(stop_b["id"],
                                                            headers=DISP))
        assert stop_b_after["status"] == "SKIPPED", (
            "the cancel must flip the still-PLANNED stop to SKIPPED"
        )
        route_after = get_success_data(api.get_pickup_route(route["id"],
                                                            headers=DISP))
        assert route_after["status"] == "COMPLETED", (
            "with every stop in {PICKED_UP, SKIPPED} the route completes itself"
        )

    def test_cancel_leaves_route_dispatched_when_stops_remain(self, api):
        """PRD §3.1: "cancellation moves `handling_status` to `CANCELLED` and
        flips every still-`PLANNED` pickup stop referencing the shipment to
        `SKIPPED`."
        PRD §3.3: "the moment every stop on a dispatched route sits in
        `PICKED_UP` or `SKIPPED`, the route's `status` becomes `COMPLETED`
        without any explicit call."

        Design: Difficulty/transitive_cascade/shipment_cancel_stop_skip_cascade_depth2
        """
        origin, dest = make_terminal_pair()
        s_a = make_shipment(origin["id"], dest["id"], actual_weight_lbs=500)
        s_b = make_shipment(origin["id"], dest["id"], actual_weight_lbs=700)
        route = make_route(origin["id"])
        add_stop(route["id"], s_a["id"], stop_sequence=1,
                 planned_arrival_minute=540)
        stop_b = add_stop(route["id"], s_b["id"], stop_sequence=2,
                          planned_arrival_minute=560)
        validate_success(api.dispatch_route(route["id"], headers=DISP))

        validate_success(api.cancel_shipment(s_b["id"], headers=DISP))
        stop_b_after = get_success_data(api.get_pickup_stop(stop_b["id"],
                                                            headers=DISP))
        assert stop_b_after["status"] == "SKIPPED"
        route_after = get_success_data(api.get_pickup_route(route["id"],
                                                            headers=DISP))
        assert route_after["status"] == "DISPATCHED", (
            "a stop still PLANNED keeps the route from completing"
        )

    def test_cancel_manifested_shipment_rejected(self, api):
        """PRD §3.1: "A dispatcher may cancel a shipment while it is `TENDERED` or
        `ON_DOCK`, provided no `ACTIVE` manifest entry references it;
        cancellation moves `handling_status` to `CANCELLED` and flips every
        still-`PLANNED` pickup stop referencing the shipment to `SKIPPED`. A
        shipment already manifested is past the point of cancellation."
        PRD §2.8: "5. Entity state preconditions for the requested transition
        (e.g. trailer must be `LOADING` to accept a manifest entry, a stop must
        be `ARRIVED` to complete, a leg must be `EN_ROUTE` to arrive) →
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_manifested_shipment_rejected
        """
        origin, dest = make_terminal_pair()
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=500)
        trailer = make_trailer(origin["id"], dest["id"], door_number=35)
        add_manifest_entry(trailer["id"], ctx["shipment"]["id"])
        resp = api.cancel_shipment(ctx["shipment"]["id"], headers=DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        shipment = get_success_data(api.get_shipment(ctx["shipment"]["id"],
                                                     headers=DISP))
        assert shipment["handling_status"] == "MANIFESTED"


class TestRouteRbac:
    def test_rating_clerk_cannot_dispatch_route(self, api):
        """PRD §2.1: "A request whose role is valid but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /ltl/pickup-routes/{routeId}/dispatch is authorized for
        Dispatcher only.

        Design: Corner/rbac/rating_clerk_cannot_dispatch_route
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], actual_weight_lbs=500)
        route = make_route(origin["id"])
        add_stop(route["id"], shipment["id"])
        resp = api.dispatch_route(route["id"],
                                  headers=TEST_USERS["rating_clerk_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        route_after = get_success_data(api.get_pickup_route(route["id"],
                                                            headers=DISP))
        assert route_after["status"] == "PLANNED"
