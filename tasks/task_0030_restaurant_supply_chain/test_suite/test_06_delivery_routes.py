"""DeliveryRoute lifecycle: plan, dispatch, depart, complete, exception,
reroute.

PRD §3.4 references throughout. Validates dispatch preconditions
(vehicle availability, capacity, temperature zones, batch readiness,
overlap), driver-match enforcement, and the IN_TRANSIT → EXCEPTION →
REROUTED → IN_TRANSIT cycle.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    add_hours,
    api_client,
    complete_route,
    create_recipe,
    create_route_payload,
    create_store,
    create_vehicle,
    depart_route,
    dispatch_route,
    list_inventory_batches,
    make_driver_headers,
    make_planner_headers,
    plan_route,
    planned_stop,
    raise_route_exception,
    reroute_to_replacement,
    setup_completed_batch,
    setup_delivered_inventory,
    unique_user_id,
    validate_error,
)


# ===========================================================================
# Dispatch preconditions
# ===========================================================================
class TestDispatch:
    def test_dispatch_requires_completed_batch(self, api, planner_headers):
        """PRD §3.4: 'Every loaded ProductionBatch must be in COMPLETED
        state; otherwise ERR_BATCH_NOT_READY.'

        Claim: planning a route loading a non-COMPLETED batch causes
        dispatch to fail with ERR_BATCH_NOT_READY.
        """
        advance_clock("2026-05-11T00:00:00.000Z")
        recipe = create_recipe(
            shelf_life_hours=72,
            production_minutes_per_unit=1.0,
            equipment_class="OVEN",
            temperature_zone="AMBIENT",
        )
        store = create_store(
            catalog_permission=[recipe["id"]],
            temperature_zone="AMBIENT",
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        # Only consolidate (not schedule/complete) so the batch is PLANNED.
        from test_helpers import setup_consolidated_batch
        _order, batch = setup_consolidated_batch(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-05-12",
            quantity=1,
        )
        vehicle = create_vehicle(
            capacity_units=10, temperature_zones=["AMBIENT"]
        )
        driver_id = unique_user_id("driver")
        stops = [planned_stop(
            store_id=store["id"],
            time_window_start="2026-05-12T10:00:00.000Z",
            time_window_end="2026-05-12T11:00:00.000Z",
            batch_ids=[batch["id"]],
        )]
        # Plan may succeed or fail; if it fails for the same reason,
        # still acceptable. Otherwise, dispatch must fail.
        plan_res = api.create_delivery_route(
            create_route_payload(
                vehicle_id=vehicle["id"],
                driver_user_id=driver_id,
                target_delivery_date="2026-05-12",
                planned_stops=stops,
            ),
            planner_headers,
        )
        if plan_res.status_code >= 400:
            validate_error(plan_res, "ERR_BATCH_NOT_READY")
            return
        route = plan_res.json()["data"]
        res = api.dispatch_route(route["id"], planner_headers)
        validate_error(res, "ERR_BATCH_NOT_READY")

    def test_dispatch_temperature_zone_incompatible(
        self, api, planner_headers
    ):
        """PRD §3.4: 'The route's required_zones must be a subset of the
        vehicle's temperature_zones; otherwise ERR_TEMPERATURE_ZONE_INCOMPATIBLE.'

        Claim: a CHILLED recipe loaded onto a vehicle whose
        temperature_zones list contains only AMBIENT → ERR_TEMPERATURE_ZONE_INCOMPATIBLE.
        """
        advance_clock("2026-05-11T00:00:00.000Z")
        recipe = create_recipe(
            shelf_life_hours=72,
            production_minutes_per_unit=1.0,
            equipment_class="OVEN",
            temperature_zone="CHILLED",
        )
        store = create_store(
            catalog_permission=[recipe["id"]],
            temperature_zone="MIXED",
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        _order, batch = setup_completed_batch(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-05-12",
            quantity=1,
        )
        vehicle = create_vehicle(
            capacity_units=10, temperature_zones=["AMBIENT"]
        )
        driver_id = unique_user_id("driver")
        stops = [planned_stop(
            store_id=store["id"],
            time_window_start=add_hours(batch["produced_at"], 1),
            time_window_end=add_hours(batch["produced_at"], 2),
            batch_ids=[batch["id"]],
        )]
        # Plan may succeed (zone check happens at dispatch per §3.4) or
        # may fail at plan time. If plan fails for the same reason,
        # accept that.
        plan_res = api.create_delivery_route(
            create_route_payload(
                vehicle_id=vehicle["id"],
                driver_user_id=driver_id,
                target_delivery_date="2026-05-12",
                planned_stops=stops,
            ),
            planner_headers,
        )
        if plan_res.status_code >= 400:
            validate_error(plan_res, "ERR_TEMPERATURE_ZONE_INCOMPATIBLE")
            return
        route = plan_res.json()["data"]
        res = api.dispatch_route(route["id"], planner_headers)
        validate_error(res, "ERR_TEMPERATURE_ZONE_INCOMPATIBLE")


# ===========================================================================
# Driver match
# ===========================================================================
class TestDriverMatch:
    def test_depart_with_wrong_driver_id_rejected(self, api):
        """PRD §3.4: 'The driver subsequently transitions the route from
        DISPATCHED to IN_TRANSIT by departing — the request requires
        X-User-ID to match driver_user_id (otherwise ERR_DRIVER_MISMATCH).'

        Claim: depart with X-User-ID different from the route's
        driver_user_id → ERR_DRIVER_MISMATCH.
        """
        advance_clock("2026-05-11T00:00:00.000Z")
        recipe = create_recipe(
            shelf_life_hours=72,
            production_minutes_per_unit=1.0,
            equipment_class="OVEN",
            temperature_zone="AMBIENT",
        )
        store = create_store(
            catalog_permission=[recipe["id"]],
            temperature_zone="AMBIENT",
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        _order, batch = setup_completed_batch(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-05-12",
            quantity=1,
        )
        vehicle = create_vehicle(
            capacity_units=10, temperature_zones=["AMBIENT"]
        )
        owner_driver = unique_user_id("driver-owner")
        intruder = unique_user_id("driver-intruder")
        stops = [planned_stop(
            store_id=store["id"],
            time_window_start=add_hours(batch["produced_at"], 1),
            time_window_end=add_hours(batch["produced_at"], 2),
            batch_ids=[batch["id"]],
        )]
        route = plan_route(
            vehicle_id=vehicle["id"],
            driver_user_id=owner_driver,
            target_delivery_date="2026-05-12",
            planned_stops=stops,
        )
        dispatch_route(route["id"])
        res = api.depart_route(route["id"], make_driver_headers(intruder))
        validate_error(res, "ERR_DRIVER_MISMATCH")


# ===========================================================================
# Completion side effects (route → InventoryBatch → DELIVERED)
# ===========================================================================
class TestCompletionCascade:
    def test_complete_creates_inventory_and_advances_orders(self):
        """PRD §3.4: 'Completion (IN_TRANSIT to COMPLETED) ... creates
        one InventoryBatch per stop at the receiving store (with
        store_id set from the stop, recipe_id and production_batch_id
        from the loaded batch, an initial quantity_on_hand equal to the
        loaded units, received_at stamped to now, expires_at copied from
        the originating ProductionBatch.expires_at, an alert_tier of
        NONE, and status of ON_HAND), and transitions every linked
        StoreOrder from CONSOLIDATED to DELIVERED.'

        Claim: after route complete, an InventoryBatch with
        quantity_on_hand == loaded units exists, and the linked
        StoreOrder has status == DELIVERED.
        """
        advance_clock("2026-05-11T00:00:00.000Z")
        recipe = create_recipe(
            shelf_life_hours=72,
            production_minutes_per_unit=1.0,
            equipment_class="OVEN",
            temperature_zone="AMBIENT",
        )
        store = create_store(
            catalog_permission=[recipe["id"]],
            temperature_zone="AMBIENT",
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        order, batch, route, inv = setup_delivered_inventory(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-05-12",
            quantity=5,
            vehicle_temp_zones=["AMBIENT"],
        )
        assert inv["status"] == "ON_HAND"
        assert inv["quantity_on_hand"] == 5
        assert inv["alert_tier"] == "NONE"
        from test_helpers import get_order
        refreshed = get_order(order["id"])
        assert refreshed["status"] == "DELIVERED"
