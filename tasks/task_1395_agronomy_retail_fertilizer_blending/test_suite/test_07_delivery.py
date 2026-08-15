"""Delivery: trucks, routes, stops, and capacity enforcement."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, DISPATCH, PLANT, CREDIT,
    create_truck_payload, create_delivery_route_payload, add_stop_payload,
    setup_batched_order)

UREA_SPEC = {"name": "UREA 46-0-0", "analysis_n_pct": 46, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}


def _batched_ctx(api, field_acres=125, rate=400.0, n_cap=300, lot_tons=30):
    return setup_batched_order(
        field_acres=field_acres,
        n_cap_lbs_per_acre=n_cap,
        products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
        lots={"UREA 46-0-0": lot_tons}, with_blender=True,
        lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": rate}])


class TestRouteDispatchPreconditions:
    def test_dispatch_requires_at_least_one_stop(self, api):
        """PRD 3.7: "Dispatch (`PLANNED → DISPATCHED`) requires the route to be
        `PLANNED`, to carry at least one `PLANNED` stop, and to ride an `ACTIVE`
        truck; violations surface as `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/route_dispatch_requires_at_least_one_stop
        """
        truck = get_success_data(api.create_truck(create_truck_payload(name="TRUCK-E"), DISPATCH))
        route = get_success_data(api.create_delivery_route(
            create_delivery_route_payload(truck_id=truck["id"]), DISPATCH))
        resp = api.dispatch_route(route["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        readback = get_success_data(api.get_delivery_route(route["id"], DISPATCH))
        assert readback["status"] == "PLANNED"


class TestDuplicateRoute:
    def test_duplicate_route_for_truck_date_rejected(self, api):
        """PRD 3.7: "At most one non-`CANCELLED` route may exist per truck per date;
        a duplicate attempt fails with `ERR_DUPLICATE_ROUTE_FOR_TRUCK_DATE`
        (HTTP 409)."

        Design: Corner/errors/error_duplicate_route_for_truck_date_trigger
        """
        truck = get_success_data(api.create_truck(create_truck_payload(name="TRUCK-D"), DISPATCH))
        get_success_data(api.create_delivery_route(
            create_delivery_route_payload(truck_id=truck["id"], route_date="2026-08-20"), DISPATCH))
        resp = api.create_delivery_route(
            create_delivery_route_payload(truck_id=truck["id"], route_date="2026-08-20"), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROUTE_FOR_TRUCK_DATE)


class TestTruckCapacityBoundary:
    def test_capacity_exact_equality_admitted_excess_rejected(self, api):
        """PRD 3.7: "Capacity is enforced at the boundary: the route's
        `total_stop_tons` after adding the stop must not exceed the truck's
        `capacity_tons` — equality admitted, excess rejected with
        `ERR_TRUCK_CAPACITY_EXCEEDED`."
        PRD 3.7: "Adding a stop snapshots the order's `tons_total` into `stop_tons`,
        adds it to the route's `total_stop_tons`, and drives the order `BATCHED →
        LOADED`."

        Design: Difficulty/boundary_precision_check/truck_capacity_exact_equality_admitted
        """
        ctx_e = _batched_ctx(api, field_acres=125, rate=400.0, n_cap=300, lot_tons=30)
        order_e = get_success_data(api.get_blend_order(ctx_e["order"]["id"], CREDIT))
        assert order_e["fulfillment_status"] == "BATCHED"

        # second tiny order on the same field: 0.1 lb/ac x 125 ac = 0.006 t
        from test_helpers import create_blend_order, book_order, create_batch_payload
        grower = ctx_e["grower"]
        order_f = create_blend_order(
            grower, ctx_e["field"]["id"], ctx_e["recommendation"]["id"], 125,
            [{"product_id": ctx_e["products"]["UREA 46-0-0"]["id"], "target_rate_lbs_per_acre": 0.1}])
        book_order(order_f["id"], grower)
        batch_f = get_success_data(api.create_batch(
            order_f["id"],
            create_batch_payload(blender_id=ctx_e["blender"]["id"],
                                 scheduled_start="2026-08-05T09:30:00Z",
                                 scheduled_end="2026-08-05T09:45:00Z"),
            PLANT))
        get_success_data(api.start_batch(batch_f["id"], PLANT))
        from test_helpers import order_line_ids
        ln_f = order_line_ids(order_f["id"])[0]
        get_success_data(api.complete_batch(batch_f["id"], {
            "actuals": [{"blend_line_id": ln_f, "actual_rate_lbs_per_acre": 0.1}],
        }, PLANT))

        truck = get_success_data(api.create_truck(create_truck_payload(name="TRUCK-25", capacity_tons=25), DISPATCH))
        route = get_success_data(api.create_delivery_route(
            create_delivery_route_payload(truck_id=truck["id"], route_date="2026-08-20"), DISPATCH))

        stop1 = get_success_data(api.add_delivery_stop(route["id"], add_stop_payload(
            blend_order_id=order_e["id"], sequence=1,
            window_start="2026-08-20T08:00:00Z", window_end="2026-08-20T10:00:00Z"), DISPATCH))
        assert stop1["stop_tons"] == pytest.approx(25.0), \
            "exactly truck capacity: ADMITTED"

        resp = api.add_delivery_stop(route["id"], add_stop_payload(
            blend_order_id=order_f["id"], sequence=2,
            window_start="2026-08-20T10:00:00Z", window_end="2026-08-20T11:00:00Z"), DISPATCH)
        validate_error(resp, ApiErrorId.ERR_TRUCK_CAPACITY_EXCEEDED)

        route_read = get_success_data(api.get_delivery_route(route["id"], DISPATCH))
        assert route_read["total_stop_tons"] == pytest.approx(25.0), \
            "rejected stop added nothing"


    def test_stop_add_snapshots_tons_and_drives_loaded(self, api):
        """PRD 3.7: "Adding a stop snapshots the order's `tons_total` into
        `stop_tons`, adds it to the route's `total_stop_tons`, and drives the order
        `BATCHED → LOADED`."
        PRD 3.7: "the route's `total_stop_tons` after adding the stop must not exceed
        the truck's `capacity_tons` — equality admitted, excess rejected with
        `ERR_TRUCK_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/truck_capacity_exact_equality_admitted
        """
        ctx = _batched_ctx(api, field_acres=125, rate=400.0, n_cap=300, lot_tons=30)
        truck = get_success_data(api.create_truck(create_truck_payload(name="TRUCK-EXACT", capacity_tons=25), DISPATCH))
        route = get_success_data(api.create_delivery_route(
            create_delivery_route_payload(truck_id=truck["id"], route_date="2026-08-20"), DISPATCH))
        stop = get_success_data(api.add_delivery_stop(route["id"], add_stop_payload(
            blend_order_id=ctx["order"]["id"], sequence=1), DISPATCH))
        assert stop["stop_tons"] == pytest.approx(25.0)
        route_read = get_success_data(api.get_delivery_route(route["id"], DISPATCH))
        assert route_read["total_stop_tons"] == pytest.approx(25.0), "equality admitted"
        order_read = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        assert order_read["fulfillment_status"] == "LOADED"


class TestStopCompletionGuards:
    def test_stop_complete_before_dispatch_rejected(self, api):
        """PRD 3.7: "Completing a stop — allowed only while its route is `DISPATCHED`
        — moves the stop `PLANNED → DELIVERED`."
        PRD 3.5: "Any transition fired from an ineligible state is
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/stop_complete_before_dispatch_rejected
        """
        ctx = setup_batched_order(
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20}, with_blender=True,
            lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}])
        truck = get_success_data(api.create_truck(create_truck_payload(name="TRUCK-1"), DISPATCH))
        route = get_success_data(api.create_delivery_route(
            create_delivery_route_payload(truck_id=truck["id"], route_date="2026-08-20"), DISPATCH))
        stop = get_success_data(api.add_delivery_stop(route["id"], add_stop_payload(
            blend_order_id=ctx["order"]["id"], sequence=1), DISPATCH))

        resp = api.complete_delivery_stop(stop["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        readback = get_success_data(api.get_delivery_stop(stop["id"], DISPATCH))
        assert readback["status"] == "PLANNED"
