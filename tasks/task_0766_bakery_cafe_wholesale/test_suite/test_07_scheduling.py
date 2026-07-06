"""Interval-overlap rules for route stops and oven bake slots, plus stop uniqueness."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, setup_committed_line, setup_committed_line_with_account,
    make_delivery_order, make_oven, make_bake_lot, make_route, add_stop,
    get_route, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


class TestRouteStopWindowOverlap:
    def _route_with_two_stops(self, api):
        ctx = setup_committed_line_with_account(api, par_qty=30,
                                                production_date="2026-06-13T00:00:00Z")
        orders = [make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                      ctx["line"]["id"], qty=2,
                                      delivery_date="2026-06-13T10:00:00Z") for _ in range(3)]
        route = make_route(api, route_date="2026-06-13T00:00:00Z", driver_name="Fay",
                           window_start="2026-06-13T06:00:00Z", window_end="2026-06-13T14:00:00Z")
        add_stop(api, route["id"], orders[0]["id"], sequence=1,
                 arrival_window_start="2026-06-13T08:00:00Z",
                 arrival_window_end="2026-06-13T09:00:00Z")
        add_stop(api, route["id"], orders[1]["id"], sequence=2,
                 arrival_window_start="2026-06-13T09:00:00Z",
                 arrival_window_end="2026-06-13T10:00:00Z")
        return route, orders

    def test_adjacent_touching_windows_are_accepted(self, api):
        """PRD 3.8: "A stop's arrival window is treated as half-open, so touching endpoints
        are allowed, but it must not overlap the window of any other non-cancelled stop on
        the same route".

        Design: Difficulty/resource_temporal_overlap/route_stop_window_halfopen_overlap
        """
        route, _ = self._route_with_two_stops(api)   # [08,09) then [09,10) touch at 09:00
        assert get_route(api, route["id"])["stop_count"] == 2

    def test_interior_overlap_is_rejected(self, api):
        """PRD 3.8: "it must not overlap the window of any other non-cancelled stop on the
        same route — an overlap is refused with ERR_STOP_WINDOW_OVERLAP".

        Design: Difficulty/resource_temporal_overlap/route_stop_window_halfopen_overlap
        """
        route, orders = self._route_with_two_stops(api)
        validate_error(api.add_route_stop(route["id"], {
            "delivery_order_id": orders[2]["id"], "sequence": 3,
            "arrival_window_start": "2026-06-13T08:30:00Z",
            "arrival_window_end": "2026-06-13T09:30:00Z"}, MANAGER),
            ApiErrorId.ERR_STOP_WINDOW_OVERLAP.value)
        assert get_route(api, route["id"])["stop_count"] == 2


class TestOvenSlotBufferConflict:
    def _line_and_oven(self, api):
        ctx = setup_committed_line(api, par_qty=40, production_date="2026-06-14T00:00:00Z")
        oven = make_oven(api, clean_buffer_minutes=15)
        make_bake_lot(api, ctx["line"]["id"], oven["id"], baked_qty=10,
                      produced_at="2026-06-14T09:00:00Z",
                      slot_start="2026-06-14T08:00:00Z", slot_end="2026-06-14T09:00:00Z")
        return ctx, oven

    def test_gap_smaller_than_buffer_is_rejected(self, api):
        """PRD 3.3: "requiring the oven's clean_buffer_minutes of clear separation between
        consecutive slots, any overlap — including endpoints that merely touch, or a gap
        smaller than the buffer — is rejected with ERR_OVEN_SLOT_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/oven_slot_buffer_conflict
        """
        ctx, oven = self._line_and_oven(api)   # existing slot 08:00-09:00, buffer 15 min
        validate_error(api.create_bake_lot({
            "bake_plan_line_id": ctx["line"]["id"], "oven_id": oven["id"], "baked_qty": 10,
            "produced_at": "2026-06-14T10:00:00Z",
            "slot_start": "2026-06-14T09:10:00Z",   # only a 10-minute gap after 09:00
            "slot_end": "2026-06-14T10:00:00Z"}, MANAGER),
            ApiErrorId.ERR_OVEN_SLOT_CONFLICT.value)

    def test_gap_equal_to_buffer_is_accepted(self, api):
        """PRD 3.3: "requiring the oven's clean_buffer_minutes of clear separation between
        consecutive slots, any overlap — including endpoints that merely touch, or a gap
        smaller than the buffer — is rejected with ERR_OVEN_SLOT_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/oven_slot_buffer_conflict
        """
        ctx, oven = self._line_and_oven(api)   # existing slot 08:00-09:00, buffer 15 min
        lot = validate_success(api.create_bake_lot({
            "bake_plan_line_id": ctx["line"]["id"], "oven_id": oven["id"], "baked_qty": 10,
            "produced_at": "2026-06-14T10:00:00Z",
            "slot_start": "2026-06-14T09:15:00Z",   # exactly a 15-minute gap after 09:00
            "slot_end": "2026-06-14T10:00:00Z"}, MANAGER), expected_status=201)
        assert lot["status"] == "FRESH", lot


class TestStopUniqueness:
    def test_second_stop_for_same_order_is_rejected(self, api):
        """PRD 3.8: "at most one non-cancelled stop may reference a given delivery order; a
        second is refused with ERR_DUPLICATE_STOP."

        Design: Corner/validations/duplicate_stop_for_same_order_returns_error
        """
        ctx = setup_committed_line_with_account(api, par_qty=20,
                                                production_date="2026-06-26T00:00:00Z")
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=2,
                                    delivery_date="2026-06-26T10:00:00Z")
        route = make_route(api, route_date="2026-06-26T00:00:00Z", driver_name="Gil",
                           window_start="2026-06-26T06:00:00Z", window_end="2026-06-26T14:00:00Z")
        add_stop(api, route["id"], order["id"], sequence=1,
                 arrival_window_start="2026-06-26T08:00:00Z",
                 arrival_window_end="2026-06-26T09:00:00Z")
        validate_error(api.add_route_stop(route["id"], {
            "delivery_order_id": order["id"], "sequence": 2,
            "arrival_window_start": "2026-06-26T10:00:00Z",
            "arrival_window_end": "2026-06-26T11:00:00Z"}, MANAGER),
            ApiErrorId.ERR_DUPLICATE_STOP.value)


class TestRouteWindowWellFormedness:
    def test_route_window_end_before_start_is_rejected(self, api):
        """PRD 2.5: "Wherever an interval is defined by a start and an end, the end must be
        strictly after the start; a violation is rejected with ERR_INVALID_WINDOW."

        Design: Corner/validations/route_window_end_before_start_returns_invalid_window
        """
        validate_error(api.create_delivery_route({
            "route_date": "2026-06-27T00:00:00Z", "driver_name": "Hal",
            "window_start": "2026-06-27T14:00:00Z",
            "window_end": "2026-06-27T06:00:00Z"}, MANAGER),
            ApiErrorId.ERR_INVALID_WINDOW.value)
