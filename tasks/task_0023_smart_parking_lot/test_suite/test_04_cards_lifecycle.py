"""Card issuance, suspend/reactivate cycle, expiry, and transfer (PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    assert_card,
    create_card,
    create_card_payload,
    create_vehicle,
    bind_vehicle_to_card,
    recharge_card,
    run_sweep,
    transfer_card_payload,
    unique_external_ref,
    unique_holder_ref,
    validate_error,
    validate_success,
)


class TestCardIssuance:
    def test_card_starts_active_with_zero_balance(self, api, operator_headers):
        """PRD §3.3: 'New cards are issued in ACTIVE status with balance_cents
        zero and bound_vehicle_ids empty.'"""
        res = api.create_card(
            create_card_payload(card_type="STORED_VALUE"), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert_card(data)
        assert data["status"] == "ACTIVE"
        assert data["balance_cents"] == 0
        assert data["bound_vehicle_ids"] == []

    def test_get_card_exposes_finalized_balance(self, api, operator_headers):
        """PRD §3.3: 'Reads return the card with two balance views:
        balance_cents is the provisional balance ... The companion
        finalized_balance_cents runs the identical chronological accumulator
        over the same card but excludes payments whose subject lifecycle is
        non-terminal.'"""
        card = create_card(card_type="STORED_VALUE")
        res = api.get_card(card["id"], operator_headers)
        data = validate_success(res, expected_status=200)
        assert "balance_cents" in data
        assert "finalized_balance_cents" in data


class TestCardSuspendCycle:
    def test_suspend_active_card(self, api, operator_headers):
        """PRD §3.3: 'An Operator may suspend an ACTIVE card.'"""
        card = create_card(card_type="STORED_VALUE")
        res = api.suspend_card(card["id"], operator_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "SUSPENDED"

    def test_reactivate_suspended_card(self, api, operator_headers):
        """PRD §3.3: 'the operator may then reactivate a SUSPENDED card back
        to ACTIVE.'"""
        card = create_card(card_type="STORED_VALUE")
        api.suspend_card(card["id"], operator_headers)
        res = api.reactivate_card(card["id"], operator_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ACTIVE"

    def test_suspend_already_suspended_card_rejected(self, api, operator_headers):
        """PRD §3.3: 'An Operator may suspend an ACTIVE card.' (precondition)
        PRD §2.7: state-machine eligibility check yields ERR_INVALID_STATE."""
        card = create_card(card_type="STORED_VALUE")
        api.suspend_card(card["id"], operator_headers)
        res = api.suspend_card(card["id"], operator_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_reactivate_active_card_rejected(self, api, operator_headers):
        """PRD §3.3: 'reactivate a SUSPENDED card.' (precondition)
        PRD §2.7: state-machine eligibility yields ERR_INVALID_STATE."""
        card = create_card(card_type="STORED_VALUE")
        res = api.reactivate_card(card["id"], operator_headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestCardExpiry:
    def test_clock_advance_past_valid_until_expires_card(
        self, api, operator_headers
    ):
        """PRD §3.3: 'When the current instant moves beyond valid_until ...
        an ACTIVE or SUSPENDED card transitions to EXPIRED; on this terminal
        transition every binding is cleared (bound_vehicle_ids becomes empty)
        and auto_pay_enabled is forced to false.'"""
        advance_clock("2026-12-01T00:00:00.000Z")
        card = create_card(
            card_type="STORED_VALUE",
            valid_from="2026-01-01T00:00:00.000Z",
            valid_until="2026-12-31T23:59:59.000Z",
            auto_pay_enabled=True,
        )
        vehicle = create_vehicle()
        bind_vehicle_to_card(card["id"], vehicle["id"])
        # Advance past valid_until.
        advance_clock("2027-01-02T00:00:00.000Z")
        run_sweep()
        # Re-read card.
        res = api.get_card(card["id"], operator_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "EXPIRED"
        assert data["bound_vehicle_ids"] == []
        assert data["auto_pay_enabled"] is False


class TestCardTransfer:
    def test_transfer_between_storedvalue_same_holder(
        self, api, operator_headers
    ):
        """PRD §3.3: 'Transferring a card moves balance and bindings from a
        source card to another card belonging to the same holder_ref ...
        On success, the target's balance_cents increases by the source's
        balance_cents, the source's balance_cents is set to zero.'"""
        holder = unique_holder_ref("HLD")
        source = create_card(card_type="STORED_VALUE", holder_ref=holder)
        target = create_card(card_type="STORED_VALUE", holder_ref=holder)
        recharge_card(
            source["id"],
            amount_cents=2500,
            external_ref=unique_external_ref("rch"),
        )
        res = api.transfer_card(
            source["id"],
            transfer_card_payload(
                target_card_id=target["id"], reason="moved to new card"
            ),
            operator_headers,
        )
        validate_success(res, expected_status=200)
        # Verify balances after.
        src = api.get_card(source["id"], operator_headers).json()["data"]
        tgt = api.get_card(target["id"], operator_headers).json()["data"]
        assert src["balance_cents"] == 0
        assert tgt["balance_cents"] == 2500

    def test_transfer_across_holder_refs_rejected(self, api, operator_headers):
        """PRD §3.3: 'The transfer is admitted only when ... they share the
        same holder_ref ... Any of these mismatches yields
        ERR_INVALID_CARD_TRANSFER.'"""
        source = create_card(card_type="STORED_VALUE", holder_ref="HOLDER-A")
        target = create_card(card_type="STORED_VALUE", holder_ref="HOLDER-B")
        res = api.transfer_card(
            source["id"],
            transfer_card_payload(target_card_id=target["id"], reason="x"),
            operator_headers,
        )
        validate_error(res, "ERR_INVALID_CARD_TRANSFER")

    def test_transfer_across_card_types_rejected(self, api, operator_headers):
        """PRD §3.3: 'the transfer is permitted only between like types —
        STORED_VALUE to STORED_VALUE or MONTHLY to MONTHLY. Any of these
        mismatches yields ERR_INVALID_CARD_TRANSFER.'"""
        holder = unique_holder_ref()
        source = create_card(card_type="STORED_VALUE", holder_ref=holder)
        target = create_card(card_type="MONTHLY", holder_ref=holder)
        res = api.transfer_card(
            source["id"],
            transfer_card_payload(target_card_id=target["id"], reason="x"),
            operator_headers,
        )
        validate_error(res, "ERR_INVALID_CARD_TRANSFER")

    def test_transfer_with_non_active_source_rejected(
        self, api, operator_headers
    ):
        """PRD §3.3: 'The transfer is admitted only when both source and
        target are in ACTIVE status ... Any of these mismatches yields
        ERR_INVALID_CARD_TRANSFER.'"""
        holder = unique_holder_ref()
        source = create_card(card_type="STORED_VALUE", holder_ref=holder)
        target = create_card(card_type="STORED_VALUE", holder_ref=holder)
        api.suspend_card(source["id"], operator_headers)
        res = api.transfer_card(
            source["id"],
            transfer_card_payload(target_card_id=target["id"], reason="x"),
            operator_headers,
        )
        validate_error(res, "ERR_INVALID_CARD_TRANSFER")

    def test_transfer_without_reason_rejected(self, api, operator_headers):
        """PRD §2.11: 'A missing or empty reason on any such action is
        rejected with ERR_REASON_REQUIRED.'"""
        holder = unique_holder_ref()
        source = create_card(card_type="STORED_VALUE", holder_ref=holder)
        target = create_card(card_type="STORED_VALUE", holder_ref=holder)
        res = api.transfer_card(
            source["id"],
            {"target_card_id": target["id"], "reason": ""},
            operator_headers,
        )
        validate_error(res, "ERR_REASON_REQUIRED")
