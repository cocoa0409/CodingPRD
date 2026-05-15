"""Shipment cancel — compensating action on lot stock, PRD §3.5.

Tests cover: cancel from PLANNED (no stock side effects), cancel from
PICKED (compensating restoration), and the lot unit-conservation
invariant.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lot_unit_conservation,
    assert_zone_utilization_invariant,
    cancel_shipment,
    create_planned_shipment,
    get_bin,
    get_lot,
    get_zone,
    pick_shipment,
    setup_accepted_lot,
    setup_picked_shipment,
    validate_error,
)


# ===========================================================================
# Cancel from PLANNED — no stock side effects.
# ===========================================================================
class TestCancelFromPlanned:

    def test_cancel_planned_does_not_touch_lot(self, api):
        """PRD §3.5: "A shipment may be cancelled by a `Picker` from
        `PLANNED` (no stock side effects, since no pick has occurred)".

        Claim: cancel a PLANNED shipment; the lot's quantity_on_hand
        and quantity_picked are unchanged.
        """
        ctx = setup_accepted_lot(quantity_units=10)
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"],
            quantity_units=4,
        )
        lot_before = get_lot(ctx["lot"]["id"])
        cancelled = cancel_shipment(s["id"])
        assert cancelled["status"] == "CANCELLED"
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["quantity_on_hand"] == lot_before["quantity_on_hand"]
        assert lot_after["quantity_picked"] == lot_before["quantity_picked"]


# ===========================================================================
# Cancel from PICKED — compensating restoration.
# # difficulty: compensating_invariant/lot_units_conserved_on_pick_then_cancel
# ===========================================================================
class TestCancelFromPicked:

    def test_cancel_restores_lot_to_allow_second_pick(self, api):
        """PRD §3.5: "or from `PICKED` (the previously decremented
        stock is restored — the picked lot's `quantity_on_hand` rises
        by the shipment's `quantity_units` and `quantity_picked`
        falls by the same amount, with bin and zone utilisation
        recomputed)."

        Difficulty-design: compensating_invariant /
        lot_units_conserved_on_pick_then_cancel (downstream side —
        after a cancel restores stock, a fresh shipment can pick the
        same lot again, proving the restoration is complete and
        symmetric to the original decrement).
        # difficulty: compensating_invariant/lot_units_conserved_on_pick_then_cancel

        Claim: pick 4 from a 10-unit lot → cancel → a second
        shipment for 4 units picks the same lot again successfully.
        """
        ctx = setup_picked_shipment(
            quantity_units=4, accepted_quantity_units=10,
        )
        cancel_shipment(ctx["shipment"]["id"])
        # Lot is now fully restored.
        lot_after_cancel = get_lot(ctx["lot"]["id"])
        assert lot_after_cancel["quantity_on_hand"] == 10
        # A second shipment requesting 4 units should pick OK.
        s2 = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"], quantity_units=4,
        )
        picked2 = pick_shipment(s2["id"])
        assert picked2["status"] == "PICKED"
        # Lot now reflects the second decrement.
        lot_after_repick = get_lot(ctx["lot"]["id"])
        assert lot_after_repick["quantity_on_hand"] == 6
        assert lot_after_repick["quantity_picked"] == 4

    def test_cancel_picked_restores_lot_stock(self, api):
        """PRD §3.5: "or from `PICKED` (the previously decremented
        stock is restored — the picked lot's `quantity_on_hand` rises
        by the shipment's `quantity_units` and `quantity_picked` falls
        by the same amount, with bin and zone utilisation recomputed)."

        Difficulty-design: compensating_invariant /
        lot_units_conserved_on_pick_then_cancel.
        # difficulty: compensating_invariant/lot_units_conserved_on_pick_then_cancel

        Claim: pick 4 from a lot of 10, then cancel — lot returns to
        on_hand=10, picked=0. Total (on_hand + picked) is invariant at
        10 the whole way through.
        """
        ctx = setup_picked_shipment(
            quantity_units=4, accepted_quantity_units=10,
        )
        # After pick: on_hand=6, picked=4. (Total=10 — invariant holds.)
        lot_after_pick = get_lot(ctx["lot"]["id"])
        assert lot_after_pick["quantity_on_hand"] == 6
        assert lot_after_pick["quantity_picked"] == 4
        assert_lot_unit_conservation(lot_after_pick, initial_quantity=10)
        # Cancel — restore.
        cancelled = cancel_shipment(ctx["shipment"]["id"])
        assert cancelled["status"] == "CANCELLED"
        lot_after_cancel = get_lot(ctx["lot"]["id"])
        assert lot_after_cancel["quantity_on_hand"] == 10
        assert lot_after_cancel["quantity_picked"] == 0
        assert_lot_unit_conservation(lot_after_cancel, initial_quantity=10)


# ===========================================================================
# Lot unit conservation invariant — PRD §3.5
# ===========================================================================
class TestLotUnitConservationInvariant:

    def test_lot_conservation_holds_after_accept_and_pick(self, api):
        """PRD §3.5: "The compensating cancel preserves an invariant
        that holds at all times for every lot: the lot's
        `quantity_on_hand` plus its `quantity_picked` is always equal
        to the original receipt's `quantity_units` that minted the
        lot."

        Claim: after accept (mints lot with on_hand=Q, picked=0),
        invariant holds; after pick of P units, invariant still holds
        (on_hand=Q-P, picked=P, total=Q).
        """
        ctx = setup_accepted_lot(quantity_units=10)
        lot_at_accept = ctx["lot"]
        assert_lot_unit_conservation(lot_at_accept, initial_quantity=10)
        # Pick 3.
        s = create_planned_shipment(
            ctx["warehouse"]["id"], ctx["product"]["id"], quantity_units=3,
        )
        pick_shipment(s["id"])
        lot_after_pick = get_lot(ctx["lot"]["id"])
        assert_lot_unit_conservation(lot_after_pick, initial_quantity=10)
        assert lot_after_pick["quantity_on_hand"] == 7
        assert lot_after_pick["quantity_picked"] == 3


# ===========================================================================
# Cancel state-precondition guard.
# ===========================================================================
class TestCancelStatePrecondition:

    def test_cancel_dispatched_shipment_rejected(self, api):
        """PRD §3.5: "A request to drive a shipment through a
        transition that does not match its current `status` is
        rejected with `ERR_SHIPMENT_STATE_INVALID` (HTTP 409)."

        Claim: cancel on a DISPATCHED shipment → ERR_SHIPMENT_STATE_INVALID.
        """
        from test_helpers import setup_dispatched_shipment
        ctx = setup_dispatched_shipment(
            quantity_units=1, accepted_quantity_units=5,
        )
        res = api.cancel_shipment(
            ctx["shipment"]["id"], TEST_USERS["picker_headers"],
        )
        validate_error(res, ApiErrorId.ERR_SHIPMENT_STATE_INVALID.value)
