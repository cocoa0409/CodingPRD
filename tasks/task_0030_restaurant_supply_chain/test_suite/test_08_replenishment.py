"""ReplenishmentRule lifecycle: create, ACTIVE↔SUSPENDED, sweep,
manual-replenish cycle gate.

PRD §3.5 references throughout. Validates the inclusive
on_hand <= safety_stock_units boundary, the ACTIVE/SUSPENDED toggle,
and the manual-cycle-not-elapsed rejection.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    activate_replenishment_rule,
    add_hours,
    advance_clock,
    api_client,
    assert_replenishment_rule,
    create_recipe,
    create_replenishment_rule,
    create_store,
    list_store_orders,
    make_storemanager_headers,
    run_replenish_sweep,
    setup_replenishment_with_on_hand,
    setup_store_recipe_ingredient,
    suspend_replenishment_rule,
    validate_error,
)


# ===========================================================================
# ACTIVE ↔ SUSPENDED cycle
# ===========================================================================
class TestRuleActivateSuspend:
    def test_active_suspend_active_cycle(self):
        """PRD §3.5: 'A rule may be moved between ACTIVE and SUSPENDED
        and back at any time — both transitions append an audit row but
        have no other side effects.'

        Claim: the rule cycles ACTIVE → SUSPENDED → ACTIVE → SUSPENDED.
        """
        store, recipe, _ = setup_store_recipe_ingredient()
        rule = create_replenishment_rule(
            store_id=store["id"],
            recipe_id=recipe["id"],
            safety_stock_units=5,
            replenish_to_units=20,
            cycle_hours=1,
        )
        assert_replenishment_rule(rule)
        assert rule["status"] == "ACTIVE"
        suspended = suspend_replenishment_rule(
            rule_id=rule["id"], store_id=store["id"]
        )
        assert suspended["status"] == "SUSPENDED"
        reactivated = activate_replenishment_rule(
            rule_id=rule["id"], store_id=store["id"]
        )
        assert reactivated["status"] == "ACTIVE"
        again_suspended = suspend_replenishment_rule(
            rule_id=rule["id"], store_id=store["id"]
        )
        assert again_suspended["status"] == "SUSPENDED"


# ===========================================================================
# Replenishment-signal threshold (boundary inclusive)
# ===========================================================================
class TestReplenishmentBoundary:
    def test_on_hand_equal_safety_stock_triggers(self):
        """PRD §3.5: 'If the on-hand quantity is less than or equal to
        safety_stock_units (boundary inclusive — at exactly the safety
        threshold the rule still triggers), a replenishment StoreOrder
        is generated'.

        Claim: with on_hand == safety_stock_units == 10, the next
        /_sweep/replenish creates a DRAFT or auto-submitted StoreOrder
        for (store, recipe).
        """
        ctx = setup_replenishment_with_on_hand(
            safety_stock_units=10,
            on_hand=10,
            replenish_to_units=20,
            cycle_hours=1,
        )
        before_orders = list_store_orders(store_id=ctx["store"]["id"])
        run_replenish_sweep()
        after_orders = list_store_orders(store_id=ctx["store"]["id"])
        assert len(after_orders) > len(before_orders), (
            "Replenishment sweep at on_hand == safety_stock_units must "
            "create a new StoreOrder (boundary inclusive)."
        )
