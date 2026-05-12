"""InventoryBatch lifecycle: adjust, transfer, dispose, near-expiry alert.

PRD §3.5 references throughout. Validates ON_HAND → DEPLETED via adjust
to zero, ON_HAND → TRANSFERRED_OUT for TIER1/TIER2, ON_HAND → DISPOSED
for TIER3, the TIER3-cannot-be-transferred safety rule, and the
inclusive 24-hour TIER1 boundary on the near-expiry sweep.

Note: setup_inventory_with_target_expiry() pins the simulated clock so
that distance-to-expiry equals (expires_at_iso - 2026-05-11T00:00:00Z).
Tests should NOT call advance_clock() around the fixture — the fixture
handles clock placement.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TIER1_HOURS,
    TIER2_HOURS,
    add_hours,
    adjust_inventory,
    advance_clock,
    api_client,
    create_recipe,
    create_store,
    dispose_inventory,
    list_inventory_batches,
    list_loss_records,
    make_storemanager_headers,
    parse_iso,
    run_expiry_sweep,
    setup_delivered_inventory,
    setup_inventory_with_target_expiry,
    transfer_inventory,
    transfer_inventory_payload,
    validate_error,
)


# ===========================================================================
# Adjust → DEPLETED
# ===========================================================================
class TestAdjustDeplete:
    def test_negative_delta_to_zero_marks_depleted(self):
        """PRD §3.5: 'If the resulting quantity_on_hand would equal zero
        exactly, the batch transitions from ON_HAND to DEPLETED; the
        requirement is quantity_on_hand plus delta equals zero.'

        Claim: after adjust with delta=-on_hand, status == DEPLETED.
        """
        advance_clock("2026-05-11T00:00:00.000Z")
        recipe = create_recipe(
            shelf_life_hours=720,  # plenty of headroom
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
        _order, _batch, _route, inv = setup_delivered_inventory(
            store_id=store["id"],
            recipe_id=recipe["id"],
            target_delivery_date="2026-05-12",
            quantity=4,
            vehicle_temp_zones=["AMBIENT"],
        )
        adjusted = adjust_inventory(
            inventory_batch_id=inv["id"],
            store_id=store["id"],
            delta=-4,
            reason="all sold",
        )
        assert adjusted["quantity_on_hand"] == 0
        assert adjusted["status"] == "DEPLETED"


# ===========================================================================
# Disposal auto-creates a SPOILAGE LossRecord
# ===========================================================================
class TestDisposal:
    def test_dispose_auto_creates_loss_record(self):
        """PRD §3.5: 'Disposal transitions the batch from ON_HAND to
        DISPOSED, auto-creates a LossRecord whose cause is SPOILAGE and
        whose quantity_lost equals the batch's quantity_on_hand at
        disposal time, and appends an audit row whose action is
        DISPOSE_STOCK and whose payload archives the disposal record
        immutably.'

        Claim: dispose creates one LossRecord with cause=SPOILAGE and
        quantity_lost equal to the pre-dispose quantity_on_hand.
        """
        # expires_at_iso = 2026-05-11T00:00:00Z; the fixture pins clock
        # so distance == 0h, satisfying the "now() >= expires_at"
        # mandatory-disposal alternative (PRD §3.5).
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-05-11T00:00:00.000Z",
            quantity_on_hand=3,
        )
        disposed = dispose_inventory(
            inventory_batch_id=inv["id"], store_id=store["id"]
        )
        assert disposed["status"] == "DISPOSED"
        records = list_loss_records(
            store_id=store["id"], inventory_batch_id=inv["id"]
        )
        spoilage = [r for r in records if r.get("cause") == "SPOILAGE"]
        assert len(spoilage) >= 1
        assert spoilage[0]["quantity_lost"] == 3


# ===========================================================================
# Tier transfers — TIER1 allowed; TIER3 forbidden
# ===========================================================================
class TestTierTransfer:
    def test_transfer_tier1_to_compatible_zone_succeeds(self):
        """PRD §3.5: 'Inter-store transfer is permitted from ON_HAND to
        TRANSFERRED_OUT for batches whose alert_tier is either TIER1 or
        TIER2; NONE batches have no near-expiry justification for a
        transfer and are also rejected.'

        Claim: a TIER1 batch can be transferred; the source flips to
        TRANSFERRED_OUT.
        """
        # Distance == 24h (TIER1 inclusive per PRD §3.5).
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-05-12T00:00:00.000Z",
            quantity_on_hand=2,
            recipe_temperature_zone="AMBIENT",
        )
        run_expiry_sweep()
        batches = list_inventory_batches(store_id=store["id"])
        target = next(b for b in batches if b["id"] == inv["id"])
        assert target["alert_tier"] == "TIER1"
        # Build a destination store with a compatible zone.
        dest = create_store(temperature_zone="MIXED")
        result = transfer_inventory(
            inventory_batch_id=inv["id"],
            source_store_id=store["id"],
            destination_store_id=dest["id"],
        )
        assert result["status"] == "TRANSFERRED_OUT"

    def test_transfer_tier3_rejected_with_disposal_required(self, api):
        """PRD §3.5: 'A TIER3 batch (or any batch whose expires_at is at
        or before the current instant) must be disposed of via the
        dispose action.... Transferring a TIER3 batch is forbidden — the
        request is rejected with ERR_TIER3_DISPOSAL_REQUIRED — because
        TIER3 must be disposed.'

        Claim: a TIER3 batch transfer attempt → ERR_TIER3_DISPOSAL_REQUIRED.
        """
        # Distance == -24h → TIER3.
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-05-10T00:00:00.000Z",
            quantity_on_hand=2,
            recipe_temperature_zone="AMBIENT",
        )
        run_expiry_sweep()
        # Build a destination with a compatible zone.
        dest = create_store(temperature_zone="MIXED")
        headers = make_storemanager_headers(store["id"])
        res = api.transfer_inventory_batch(
            inv["id"],
            transfer_inventory_payload(destination_store_id=dest["id"]),
            headers,
        )
        validate_error(res, "ERR_TIER3_DISPOSAL_REQUIRED")


# ===========================================================================
# Near-expiry tier boundaries (inclusive)
# ===========================================================================
class TestAlertTiers:
    def test_tier1_inclusive_at_24h(self):
        """PRD §3.5: 'Otherwise, if the distance is at most 24 hours,
        alert_tier becomes TIER1 (promotion or transfer recommended).'
        PRD §3.5: 'Boundaries are inclusive: a batch exactly 24 hours
        from expiry is TIER1, not NONE'.

        Claim: a batch whose expires_at is exactly 24 hours after now()
        is classified as TIER1 by the sweep.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-05-12T00:00:00.000Z",
            quantity_on_hand=1,
        )
        run_expiry_sweep()
        batches = list_inventory_batches(store_id=store["id"])
        target = next(b for b in batches if b["id"] == inv["id"])
        assert target["alert_tier"] == "TIER1"

    def test_tier2_inclusive_at_8h(self):
        """PRD §3.5: 'Otherwise, if the distance is at most 8 hours,
        alert_tier becomes TIER2 (also a mandatory-disposal candidate).'
        PRD §3.5: 'a batch exactly 8 hours from expiry is TIER2, not
        TIER1.'

        Claim: a batch whose expires_at is exactly 8 hours after now()
        is classified as TIER2 by the sweep.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-05-11T08:00:00.000Z",
            quantity_on_hand=1,
        )
        run_expiry_sweep()
        batches = list_inventory_batches(store_id=store["id"])
        target = next(b for b in batches if b["id"] == inv["id"])
        assert target["alert_tier"] == "TIER2"

    def test_tier3_at_or_below_zero_hours(self):
        """PRD §3.5: 'If that distance is at most zero hours, alert_tier
        becomes TIER3 (mandatory disposal).'

        Claim: a batch whose expires_at is in the past is TIER3.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-05-10T00:00:00.000Z",
            quantity_on_hand=1,
        )
        run_expiry_sweep()
        batches = list_inventory_batches(store_id=store["id"])
        target = next(b for b in batches if b["id"] == inv["id"])
        assert target["alert_tier"] == "TIER3"
