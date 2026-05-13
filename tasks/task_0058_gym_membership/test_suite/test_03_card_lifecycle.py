"""Card issuance, activation, and the basic PENDING→ACTIVE transition.

PRD §3.2.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA,
    SO,
    activate_card,
    assert_card,
    assert_wallet_transaction,
    create_funded_member,
    create_monthly_card_type,
    find_wallet_txn,
    issue_card,
    list_wallet_transactions,
    make_member_headers,
    setup_member_with_active_card,
    validate_error,
)


# ===========================================================================
# Issuance side effects (PRD §3.2)
# ===========================================================================
class TestIssueCard:

    def test_issued_card_is_pending(self, api):
        """PRD §3.2: 'The card is born in PENDING status with
        activation_date, original_expiry_date, effective_expiry_date
        all null.'"""
        ct = create_monthly_card_type(price_cents=30_000)
        m = create_funded_member(wallet_balance_cents=50_000)
        card = issue_card(ct["id"], m["id"])
        assert_card(card)
        assert card["status"] == "PENDING", (
            "PRD §3.2: card is born in PENDING status."
        )
        assert card["activation_date"] is None
        assert card["original_expiry_date"] is None
        assert card["effective_expiry_date"] is None

    def test_issuance_price_cents_pinned_at_issuance(self, api):
        """PRD §3.2: 'issuance_price_cents is copied from
        CardType.price_cents at the issuance moment.'"""
        ct = create_monthly_card_type(price_cents=45_000)
        m = create_funded_member(wallet_balance_cents=60_000)
        card = issue_card(ct["id"], m["id"])
        assert card["issuance_price_cents"] == 45_000

    def test_issuance_insufficient_balance(self, api):
        """PRD §3.4 / §3.12 priority 25: 'if principal_balance_cents is
        less than the remainder, the entire debit aborts with
        ERR_INSUFFICIENT_BALANCE'."""
        ct = create_monthly_card_type(price_cents=50_000)
        m = create_funded_member(wallet_balance_cents=10_000)
        res = api.issue_card(
            {"card_type_id": ct["id"], "holder_member_id": m["id"]},
            SO,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


# ===========================================================================
# Activation transition (PRD §3.2)
# ===========================================================================
class TestActivateCard:

    def test_activate_sets_dates(self, api):
        """PRD §3.2: 'on success the card transitions PENDING → ACTIVE,
        activation_date is set to the current instant, original_expiry_date
        is set to activation_date plus validity_days (anchored at
        end-of-day UTC), effective_expiry_date is set equal to
        original_expiry_date (no freeze yet).'"""
        _, _, card = setup_member_with_active_card(category="MONTHLY")
        assert card["status"] == "ACTIVE"
        assert card["activation_date"] is not None
        assert card["original_expiry_date"] is not None
        assert card["effective_expiry_date"] == card["original_expiry_date"], (
            "PRD §3.2: effective_expiry_date is set equal to "
            "original_expiry_date (no freeze yet)."
        )

    def test_activate_non_pending_card_rejected(self, api):
        """PRD §3.2: 'Activating a PENDING card requires the card to
        currently be PENDING.'"""
        _, _, card = setup_member_with_active_card()
        res = api.activate_card(card["id"], SO)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
