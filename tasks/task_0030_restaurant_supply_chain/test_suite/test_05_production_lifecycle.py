"""ProductionBatch lifecycle: schedule, start, complete, fail.

PRD §3.3 references throughout. Validates the PLANNED → SCHEDULED →
IN_PRODUCTION → COMPLETED / FAILED transitions, equipment-class capacity
and shelf-life sufficiency preconditions, completion side effects
(produced_at, expires_at, provisional cost allocation), and the
fail-cascade that reverts CONSOLIDATED orders.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    BATCH_SETUP_FEE_CENTS,
    EQUIPMENT_MINUTES_PER_CLASS_PER_DAY,
    advance_clock,
    complete_batch,
    consolidate_batches,
    create_recipe,
    create_store,
    fail_batch,
    get_batch,
    get_order,
    parse_iso,
    schedule_batch,
    setup_consolidated_batch,
    setup_completed_batch,
    setup_submitted_order,
    setup_two_oven_batches_capacity,
    start_batch,
    validate_error,
)


# ===========================================================================
# Completion side effects
# ===========================================================================
class TestCompletion:
    def test_complete_sets_produced_at_and_expires_at(self):
        """PRD §3.3: 'Completion transitions from IN_PRODUCTION to
        COMPLETED, stamps produced_at with the current instant, and
        computes expires_at as produced_at plus Recipe.shelf_life_hours.'

        Claim: after complete, produced_at is set and expires_at is
        produced_at + shelf_life_hours.
        """
        advance_clock("2026-05-11T00:00:00.000Z")
        recipe = create_recipe(
            shelf_life_hours=72,
            production_minutes_per_unit=1.0,
            equipment_class="OVEN",
        )
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        _order, batch = setup_completed_batch(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-05-12",
            quantity=1,
        )
        assert batch["status"] == "COMPLETED"
        assert batch["produced_at"] is not None
        assert batch["expires_at"] is not None
        produced = parse_iso(batch["produced_at"])
        expires = parse_iso(batch["expires_at"])
        delta_hours = (expires - produced).total_seconds() / 3600.0
        # Recipe.shelf_life_hours == 72.
        assert abs(delta_hours - 72.0) < 1e-3


# ===========================================================================
# Failure cascade
# ===========================================================================
class TestFailureCascade:
    def test_fail_reverts_consolidated_orders_to_submitted(self):
        """PRD §3.3: 'A failed batch transitions from IN_PRODUCTION to
        FAILED; this reverts every linked StoreOrder from CONSOLIDATED
        back to SUBMITTED and clears its consolidation_batch_id, so those
        store orders re-enter the next consolidation run.'

        Claim: after fail, every linked StoreOrder is SUBMITTED and its
        consolidation_batch_id is null.
        """
        advance_clock("2026-05-11T00:00:00.000Z")
        recipe = create_recipe(
            shelf_life_hours=72,
            production_minutes_per_unit=1.0,
            equipment_class="OVEN",
        )
        store = create_store(
            catalog_permission=[recipe["id"]],
            order_window_open_minute=0,
            order_window_close_minute=1439,
        )
        order, batch = setup_consolidated_batch(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-05-12",
            quantity=2,
        )
        scheduled = schedule_batch(batch_id=batch["id"])
        advance_clock(scheduled["scheduled_start_at"])
        started = start_batch(batch["id"])
        failed = fail_batch(started["id"])
        assert failed["status"] == "FAILED"
        refreshed = get_order(order["id"])
        assert refreshed["status"] == "SUBMITTED"
        assert refreshed.get("consolidation_batch_id") in (None, "", )
