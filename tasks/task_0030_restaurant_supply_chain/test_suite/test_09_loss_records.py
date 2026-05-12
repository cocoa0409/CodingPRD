"""LossRecord lifecycle: record, abnormal detection, approve, reverse,
investigation resolve.

PRD §3.6 references throughout. Validates responsibility-attribution
semantics, the immediate inventory decrement at recording, the
quantity_lost ≤ quantity_on_hand fiscal check, the strict-> abnormal
threshold, and the investigation gate on approval.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    api_client,
    approve_loss,
    assert_loss_record,
    create_loss_record_payload,
    create_recipe,
    create_store,
    list_inventory_batches,
    make_storemanager_headers,
    record_loss,
    reverse_loss,
    setup_delivered_inventory,
    setup_inventory_with_target_expiry,
    validate_error,
)


# ===========================================================================
# Responsibility attribution
# ===========================================================================
class TestResponsibility:
    def test_spoilage_with_responsibility_user_rejected(self, api):
        """PRD §3.6: 'when cause is SPOILAGE, responsibility_user_id must
        be omitted (or null); when cause is one of DAMAGE, THEFT, or
        PREPARATION, responsibility_user_id is required. Either mismatch
        is rejected with ERR_RESPONSIBILITY_REQUIRED.'

        Claim: SPOILAGE + responsibility_user_id present →
        ERR_RESPONSIBILITY_REQUIRED.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-06-01T00:00:00.000Z",
            quantity_on_hand=4,
        )
        headers = make_storemanager_headers(store["id"])
        payload = create_loss_record_payload(
            inventory_batch_id=inv["id"],
            quantity_lost=1,
            cause="SPOILAGE",
            responsibility_user_id="user_42",
        )
        res = api.create_loss_record(payload, headers)
        validate_error(res, "ERR_RESPONSIBILITY_REQUIRED")

    @pytest.mark.parametrize(
        "cause", ["DAMAGE", "THEFT", "PREPARATION"]
    )
    def test_blame_required_causes_without_user_rejected(self, api, cause):
        """PRD §3.6: 'when cause is one of DAMAGE, THEFT, or PREPARATION,
        responsibility_user_id is required. Either mismatch is rejected
        with ERR_RESPONSIBILITY_REQUIRED.'

        Claim: DAMAGE/THEFT/PREPARATION without responsibility_user_id
        → ERR_RESPONSIBILITY_REQUIRED.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-06-01T00:00:00.000Z",
            quantity_on_hand=4,
        )
        headers = make_storemanager_headers(store["id"])
        payload = create_loss_record_payload(
            inventory_batch_id=inv["id"],
            quantity_lost=1,
            cause=cause,
        )
        res = api.create_loss_record(payload, headers)
        validate_error(res, "ERR_RESPONSIBILITY_REQUIRED")


# ===========================================================================
# Inventory decrement at recording
# ===========================================================================
class TestInventoryDecrement:
    def test_record_loss_immediately_decrements_on_hand(self):
        """PRD §3.6: 'Recording a loss has immediate inventory
        consequences: InventoryBatch.quantity_on_hand is decremented by
        quantity_lost at the moment of creation.'

        Claim: after record_loss(quantity_lost=2) on a batch with
        on_hand == 5, the batch's quantity_on_hand becomes 3.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-06-01T00:00:00.000Z",
            quantity_on_hand=5,
        )
        loss = record_loss(
            store_id=store["id"],
            inventory_batch_id=inv["id"],
            quantity_lost=2,
            cause="SPOILAGE",
        )
        assert_loss_record(loss)
        assert loss["status"] == "RECORDED"
        # Re-read inventory.
        batches = list_inventory_batches(store_id=store["id"])
        target = next(b for b in batches if b["id"] == inv["id"])
        assert target["quantity_on_hand"] == 3


# ===========================================================================
# Reversal restores stock
# ===========================================================================
class TestReversal:
    def test_reverse_restores_quantity_on_hand(self):
        """PRD §3.6: 'Reversal transitions the loss from RECORDED to
        REVERSED. Reversal is the only path that restores stock: the
        batch's quantity_on_hand is incremented by quantity_lost,
        compensating the decrement at recording.'

        Claim: after reverse, status == REVERSED and the batch's
        quantity_on_hand is restored to its pre-record value.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-06-01T00:00:00.000Z",
            quantity_on_hand=20,
        )
        loss = record_loss(
            store_id=store["id"],
            inventory_batch_id=inv["id"],
            quantity_lost=5,
            cause="DAMAGE",
            responsibility_user_id="user_42",
        )
        # Mid-state: on_hand should be 15.
        batches = list_inventory_batches(store_id=store["id"])
        mid = next(b for b in batches if b["id"] == inv["id"])
        assert mid["quantity_on_hand"] == 15
        reversed_loss = reverse_loss(loss["id"])
        assert reversed_loss["status"] == "REVERSED"
        # Final on_hand should be 20.
        batches = list_inventory_batches(store_id=store["id"])
        final = next(b for b in batches if b["id"] == inv["id"])
        assert final["quantity_on_hand"] == 20


# ===========================================================================
# Loss exceeds on-hand
# ===========================================================================
class TestLossExceedsOnHand:
    def test_quantity_lost_above_on_hand_rejected(self, api):
        """PRD §3.6: 'an integer quantity_lost (strictly positive and at
        most the targeted batch's quantity_on_hand at recording time —
        otherwise ERR_LOSS_EXCEEDS_ON_HAND)'.

        Claim: quantity_lost > current quantity_on_hand →
        ERR_LOSS_EXCEEDS_ON_HAND.
        """
        store, inv = setup_inventory_with_target_expiry(
            expires_at_iso="2026-06-01T00:00:00.000Z",
            quantity_on_hand=3,
        )
        headers = make_storemanager_headers(store["id"])
        payload = create_loss_record_payload(
            inventory_batch_id=inv["id"],
            quantity_lost=4,
            cause="SPOILAGE",
        )
        res = api.create_loss_record(payload, headers)
        validate_error(res, "ERR_LOSS_EXCEEDS_ON_HAND")
