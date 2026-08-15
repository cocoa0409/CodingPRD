"""Replenishment order state machine, inventory anchoring, and compensating voids."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    make_plant_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_site,
    create_vessel,
    create_vessel_with_dispatched_order,
    create_vessel_with_triggered_order,
    post_reading,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]


class TestOrderHappyPath:
    def test_order_happy_path_triggered_dispatched_received(self, api):
        """PRD §3.5: "A replenishment order is always born `TRIGGERED`, either by
        the auto-trigger in §3.2 or never — there is no manual create. From
        `TRIGGERED` a `ServiceManager` may dispatch the order, advancing it to
        `DISPATCHED`; the order remains in the open-order set used by
        `flow_posture` derivation, so the vessel remains `PENDING_REPLENISHMENT`."
        PRD §3.5: "On success the order transitions to `RECEIVED` and several
        cascades fire: the vessel's `current_inventory_tons` is recomputed (the
        receipt joins the received set only when its `received_at` is strictly
        after the current anchor's `measured_at`; otherwise the receipt is already
        inside the anchor and inventory does not change), the vessel's
        `flow_posture` is recomputed (the order leaves the open-order set, so
        `PENDING_REPLENISHMENT` may clear), the parent site's `site_posture` is
        recomputed, and the vessel's `version` is bumped."

        Design: Corner/state_machines/order_happy_path_triggered_dispatched_received
        """
        site = create_site(name="HP Site", state_code="IA")
        vessel = create_vessel(
            site["id"],
            name="SILO-HP",
            capacity_tons=100,
            material_name="corn",
            reorder_point_pct=30,
            target_fill_pct=90,
        )
        # First reading anchors inventory at 60.0; second reading re-anchors to
        # 25.0 and triggers the order.
        post_reading(vessel["id"], "2026-08-02T00:00:00Z", 60.0, site["id"])
        post_reading(vessel["id"], "2026-08-03T00:00:00Z", 25.0, site["id"])
        data, meta = validate_paginated(
            api.list_replenishment_orders(
                SM, params={"vessel_id": vessel["id"], "status": "TRIGGERED"}
            )
        )
        assert meta["total_count"] == 1
        order = data[0]

        dispatched = validate_success(
            api.dispatch_replenishment_order(order["id"], SM), 200
        )
        assert dispatched["status"] == "DISPATCHED"

        received = validate_success(
            api.receive_replenishment_order(
                order["id"],
                {"delivered_tons": 12.0, "received_at": "2026-08-04T00:00:00Z"},
                make_plant_operator_headers(site["id"]),
            ),
            200,
        )
        assert received["status"] == "RECEIVED"
        assert received["delivered_tons"] == 12.0

        fetched = validate_success(api.get_vessel(vessel["id"], SM), 200)
        # anchor = 2026-08-03 reading at 25.0; receipt at 2026-08-04 > anchor -> +12.0
        assert fetched["current_inventory_tons"] == pytest.approx(37.0, abs=1e-9)
        # order left the open-order set; no quality breach -> NORMAL
        assert fetched["flow_posture"] == "NORMAL"


class TestOrderInvalidTransitions:
    def test_order_receive_from_triggered_invalid_state(self, api):
        """PRD §3.5: "Any attempt to invoke these transitions from a wrong
        from-state is rejected with `ERR_INVALID_ORDER_STATE` (HTTP 409)."
        PRD §3.5: "A `PlantOperator` (for its own site) or a `Technician` may record
        delivery of a `DISPATCHED` order by supplying `delivered_tons` (must be
        greater than zero, otherwise `ERR_VALIDATION`) and `received_at`."

        Design: Corner/state_machines/order_receive_from_triggered_invalid_state
        """
        site, vessel, order, reading = create_vessel_with_triggered_order(
            site_overrides={"name": "IS Site", "state_code": "IA"},
            vessel_overrides={
                "name": "SILO-IS",
                "capacity_tons": 100,
                "material_name": "corn",
                "reorder_point_pct": 30,
                "target_fill_pct": 90,
            },
        )
        res = api.receive_replenishment_order(
            order["id"],
            {"delivered_tons": 5.0, "received_at": "2026-08-03T00:00:00Z"},
            make_plant_operator_headers(site["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_ORDER_STATE, expected_status=409)

        fetched_order = validate_success(
            api.get_replenishment_order(order["id"], SM), 200
        )
        assert fetched_order["status"] == "TRIGGERED"
        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        assert fetched_vessel["current_inventory_tons"] == pytest.approx(
            25.0, abs=1e-9
        )

    def test_order_cancel_from_received_terminal_lockdown(self, api):
        """PRD §3.5: "A `PlantOperator` (for its own site) or a `ServiceManager` may
        cancel a `TRIGGERED` order, advancing it to `CANCELLED`."
        PRD §3.5: "Any attempt to invoke these transitions from a wrong from-state
        is rejected with `ERR_INVALID_ORDER_STATE` (HTTP 409)."

        Design: Corner/state_machines/order_cancel_from_received_terminal_lockdown
        """
        site, vessel, order, reading = create_vessel_with_dispatched_order(
            site_overrides={"name": "TL Site", "state_code": "IA"},
            vessel_overrides={
                "name": "SILO-TL",
                "capacity_tons": 100,
                "material_name": "corn",
                "reorder_point_pct": 30,
                "target_fill_pct": 90,
            },
        )
        validate_success(
            api.receive_replenishment_order(
                order["id"],
                {"delivered_tons": 5.0, "received_at": "2026-08-03T00:00:00Z"},
                make_plant_operator_headers(site["id"]),
            ),
            200,
        )
        res = api.cancel_replenishment_order(order["id"], SM)
        validate_error(res, ApiErrorId.ERR_INVALID_ORDER_STATE, expected_status=409)

        fetched_order = validate_success(
            api.get_replenishment_order(order["id"], SM), 200
        )
        assert fetched_order["status"] == "RECEIVED"
        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        assert fetched_vessel["current_inventory_tons"] == pytest.approx(
            30.0, abs=1e-9
        )

    def test_dispatch_twice_second_attempt_invalid(self, api):
        """PRD §3.5: "From `TRIGGERED` a `ServiceManager` may dispatch the order,
        advancing it to `DISPATCHED`; the order remains in the open-order set used
        by `flow_posture` derivation, so the vessel remains
        `PENDING_REPLENISHMENT`."
        PRD §3.5: "Any attempt to invoke these transitions from a wrong from-state
        is rejected with `ERR_INVALID_ORDER_STATE` (HTTP 409)."

        Design: Corner/state_machines/dispatch_twice_second_attempt_invalid
        """
        site, vessel, order, reading = create_vessel_with_dispatched_order(
            site_overrides={"name": "DT Site", "state_code": "IA"},
            vessel_overrides={
                "name": "SILO-DT",
                "capacity_tons": 100,
                "material_name": "corn",
                "reorder_point_pct": 30,
                "target_fill_pct": 90,
            },
        )
        res = api.dispatch_replenishment_order(order["id"], SM)
        validate_error(res, ApiErrorId.ERR_INVALID_ORDER_STATE, expected_status=409)
        fetched_order = validate_success(
            api.get_replenishment_order(order["id"], SM), 200
        )
        assert fetched_order["status"] == "DISPATCHED"


class TestReceiveVoidCompensation:
    def _setup_dispatched(self):
        return create_vessel_with_dispatched_order(
            site_overrides={"name": "Site Sixteen", "state_code": "TX"},
            vessel_overrides={
                "name": "SILO-V",
                "capacity_tons": 100,
                "material_name": "cement",
                "reorder_point_pct": 30,
                "target_fill_pct": 90,
                "opening_inventory_tons": 0,
            },
            reading_level_pct=25.0,
            reading_measured_at="2026-08-02T00:00:00Z",
        )

    def test_receive_adds_delivered_tons_to_anchor(self, api):
        """PRD §3.2: "The vessel's `current_inventory_tons` is then the anchor
        inventory plus the sum of `delivered_tons` across all replenishment orders
        for the vessel whose status is `RECEIVED` and whose `received_at` is
        strictly after the anchor's `measured_at`, again rounded half up to 1
        decimal place."

        Design: Difficulty/compensating_invariant/receive_then_void_restores_inventory_mass
        """
        site, vessel, order, _ = self._setup_dispatched()
        validate_success(
            api.receive_replenishment_order(
                order["id"],
                {"delivered_tons": 25.0, "received_at": "2026-08-03T00:00:00Z"},
                make_plant_operator_headers(site["id"]),
            ),
            200,
        )
        fetched = validate_success(api.get_vessel(vessel["id"], SM), 200)
        # anchor 25.0 + 25.0 (received_at 2026-08-03 > anchor 2026-08-02)
        assert fetched["current_inventory_tons"] == pytest.approx(50.0, abs=1e-9)

    def test_receive_then_void_restores_inventory_mass(self, api):
        """PRD §3.2: "A `RECEIVED` order that is later `VOIDED` simply leaves the
        received set, so receive followed by void restores the pre-receipt value
        exactly."
        PRD §3.5: "A successful void transitions the order to `VOIDED`, recomputes
        the vessel's `current_inventory_tons` without this receipt (mass-balance
        compensation), recomputes the vessel's `flow_posture` and the site's
        `site_posture`, and bumps the vessel's `version`."

        Design: Difficulty/compensating_invariant/receive_then_void_restores_inventory_mass
        """
        site, vessel, order, _ = self._setup_dispatched()
        validate_success(
            api.receive_replenishment_order(
                order["id"],
                {"delivered_tons": 25.0, "received_at": "2026-08-03T00:00:00Z"},
                make_plant_operator_headers(site["id"]),
            ),
            200,
        )
        voided = validate_success(
            api.void_replenishment_order(order["id"], SM), 200
        )
        assert voided["status"] == "VOIDED"

        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        # order left the RECEIVED set -> pre-receipt anchor value restored exactly
        assert fetched_vessel["current_inventory_tons"] == pytest.approx(
            25.0, abs=1e-9
        )
        assert fetched_vessel["flow_posture"] == "NORMAL"
        fetched_site = validate_success(api.get_site(site["id"], SM), 200)
        assert fetched_site["site_posture"] == "NORMAL"


class TestInventoryReanchorAndNegativeVoid:
    def _setup_received_then_reanchored(self):
        """Vessel: reading 25.0 -> order -> dispatch -> receive 25.0 t at
        2026-08-03 (inventory 50.0) -> newer reading 10.0 at 2026-08-04
        re-anchors inventory to 10.0."""
        site = create_site(name="NG Site", state_code="IA")
        vessel = create_vessel(
            site["id"],
            name="SILO-NG",
            capacity_tons=100,
            material_name="corn",
            reorder_point_pct=30,
            target_fill_pct=90,
        )
        post_reading(vessel["id"], "2026-08-02T00:00:00Z", 25.0, site["id"])
        data, _ = validate_paginated(
            api_client.list_replenishment_orders(
                SM, params={"vessel_id": vessel["id"], "status": "TRIGGERED"}
            )
        )
        order = data[0]
        validate_success(api_client.dispatch_replenishment_order(order["id"], SM), 200)
        validate_success(
            api_client.receive_replenishment_order(
                order["id"],
                {"delivered_tons": 25.0, "received_at": "2026-08-03T00:00:00Z"},
                make_plant_operator_headers(site["id"]),
            ),
            200,
        )
        post_reading(vessel["id"], "2026-08-04T00:00:00Z", 10.0, site["id"])
        return site, vessel, order

    def test_inventory_reanchors_on_newer_reading(self, api):
        """PRD §3.2: "The anchor for the calculation is the vessel's `LevelReading`
        with the latest `measured_at`, with ties broken by the latest `created_at`;
        if no readings exist at all, the implicit anchor is the vessel's
        `created_at` paired with `opening_inventory_tons`."
        PRD §3.2: "A receipt whose `received_at` is at or before the anchor's
        `measured_at` is understood to be already inside the anchor and contributes
        nothing."

        Design: Corner/calculations/inventory_reanchors_on_newer_reading
        """
        site, vessel, order = self._setup_received_then_reanchored()
        fetched = validate_success(api.get_vessel(vessel["id"], SM), 200)
        # Re-anchored to the 2026-08-04 reading at 10.0; the 2026-08-03 receipt is
        # at/before the new anchor and contributes nothing.
        assert fetched["current_inventory_tons"] == pytest.approx(10.0, abs=1e-9)

        data, meta = validate_paginated(
            api.list_replenishment_orders(
                SM, params={"vessel_id": vessel["id"], "status": "TRIGGERED"}
            )
        )
        assert meta["total_count"] == 1
        # 90 - 10.0 = 80.0
        assert data[0]["order_quantity_tons"] == pytest.approx(80.0, abs=1e-9)
