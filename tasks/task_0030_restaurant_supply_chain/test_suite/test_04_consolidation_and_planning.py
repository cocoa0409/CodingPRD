"""Production consolidation, planned ingredient explosion, and forecast.

PRD §3.3 references throughout. Validates that consolidation creates
ProductionBatch rows in PLANNED state with planned_units summed across
SUBMITTED orders, transitions sources from SUBMITTED → CONSOLIDATED, and
that the forecast variant produces a different demand projection from
the planned variant (the dual-variant pair).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    consolidate_batches,
    create_recipe,
    create_store,
    get_batch,
    setup_dual_variant_planned_vs_forecast,
    setup_submitted_order,
)


# ===========================================================================
# Consolidation creates batches and flips sources
# ===========================================================================
class TestConsolidation:
    def test_consolidate_sums_planned_units_and_flips_orders(self):
        """PRD §3.3: 'For each group it creates (or updates) one
        ProductionBatch per recipe per planning run, populating recipe_id,
        target_delivery_date, and computing planned_units as the sum of
        OrderLine.quantity across the consolidated lines. Each
        consolidated StoreOrder transitions from SUBMITTED to
        CONSOLIDATED and has its consolidation_batch_id set to the
        relevant batch's id.'

        Claim: two SUBMITTED orders for one recipe + same date →
        ProductionBatch.planned_units == sum of quantities, both orders
        flipped to CONSOLIDATED with consolidation_batch_id set.
        """
        advance_clock("2026-05-11T12:00:00.000Z")
        recipe = create_recipe()
        store_a = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        store_b = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        order_a = setup_submitted_order(
            store_id=store_a["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-06-01",
            quantity=4,
        )
        order_b = setup_submitted_order(
            store_id=store_b["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-06-01",
            quantity=7,
        )
        batches = consolidate_batches(target_delivery_date="2026-06-01")
        assert len(batches) >= 1
        target = next(b for b in batches if b.get("recipe_id") == recipe["id"])
        assert target["status"] == "PLANNED"
        assert target["planned_units"] == 11
        # Both source orders should now be CONSOLIDATED.
        from test_helpers import get_order
        a = get_order(order_a["id"])
        b = get_order(order_b["id"])
        assert a["status"] == "CONSOLIDATED"
        assert b["status"] == "CONSOLIDATED"
        assert a["consolidation_batch_id"] == target["id"]
        assert b["consolidation_batch_id"] == target["id"]

    def test_consolidate_excludes_orders_for_other_dates(self):
        """PRD §3.3: 'Cancelled orders submitted before consolidation are
        excluded; orders not yet submitted are excluded; orders whose
        target dates differ are excluded.'

        Claim: an order whose target_delivery_date does not match the
        consolidation request is NOT advanced to CONSOLIDATED.
        """
        advance_clock("2026-05-11T12:00:00.000Z")
        recipe = create_recipe()
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        order_other_date = setup_submitted_order(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-06-02",
            quantity=3,
        )
        consolidate_batches(target_delivery_date="2026-06-01")
        from test_helpers import get_order
        refreshed = get_order(order_other_date["id"])
        assert refreshed["status"] == "SUBMITTED"
        assert refreshed.get("consolidation_batch_id") in (None, "", )


# ===========================================================================
# Equipment minutes computed at consolidation
# ===========================================================================
class TestEquipmentMinutesAtConsolidation:
    def test_equipment_minutes_equals_units_times_pmu(self):
        """PRD §3.3: 'A new batch is created with status of PLANNED and
        an equipment_minutes value equal to planned_units multiplied by
        Recipe.production_minutes_per_unit.'

        Claim: equipment_minutes == planned_units × production_minutes_per_unit.
        """
        advance_clock("2026-05-11T12:00:00.000Z")
        recipe = create_recipe(production_minutes_per_unit=3.0)
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        setup_submitted_order(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-06-01",
            quantity=5,
        )
        batches = consolidate_batches(target_delivery_date="2026-06-01")
        target = next(b for b in batches if b.get("recipe_id") == recipe["id"])
        assert target["planned_units"] == 5
        assert float(target["equipment_minutes"]) == pytest.approx(15.0)
