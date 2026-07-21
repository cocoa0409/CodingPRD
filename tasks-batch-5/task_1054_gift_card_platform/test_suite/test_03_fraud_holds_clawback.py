"""Fraud holds: the ACTIVE<->SUSPENDED cycle, the clear-vs-confirm branch, the
clawback reversal, balance conservation, and the confirm->settlement cascade.

Covers Difficulty non_linear_state_machine, transitive_cascade (fraud),
compensating_invariant (card balance) and Corner segregation-of-duties (fraud).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_fraud_analyst_headers,
    setup_active_card_with_open_hold, setup_multi_active_cards,
    setup_settlement_cascade_pending_confirm,
    redeem, open_hold, api_client,
)

ANY = TEST_USERS["any_headers"]
ANALYST_2 = make_fraud_analyst_headers("analyst-2")


# ─────────── Difficulty: GiftCard ACTIVE<->SUSPENDED cycle ───────────

def test_open_hold_suspends_card(api):
    """PRD §3.5: "Opening a hold is permitted only while the card is `ACTIVE` (else `ERR_INVALID_STATE`); it records the analyst's `X-User-ID` as `opened_by_user_id`, sets the hold's `resolved_by_user_id` null, starts the hold in `OPEN` status, and freezes the card by moving it from `ACTIVE` to `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/giftcard_active_suspended_cycle
    """
    _merchant, _program, card, hold = setup_active_card_with_open_hold(100000, reason="MANUAL")
    assert card["status"] == "SUSPENDED"
    assert hold["status"] == "OPEN"


def test_clear_hold_returns_card_to_active(api):
    """PRD §3.5: "**Clearing** (the benign branch) is permitted only while the hold is `OPEN` (else `ERR_INVALID_STATE`); it records the acting analyst's `X-User-ID` as `resolved_by_user_id`, moves the hold to the terminal `CLEARED` state, and unfreezes the card by returning it from `SUSPENDED` to `ACTIVE` with no change to the ledger."

    Design: Difficulty/non_linear_state_machine/giftcard_active_suspended_cycle
    """
    _merchant, _program, card, hold = setup_active_card_with_open_hold(100000, reason="MANUAL")
    cleared = validate_success(
        api.clear_fraud_hold(hold["id"], make_fraud_analyst_headers("analyst-1")), 200)
    assert cleared["status"] == "CLEARED"
    card_after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert card_after["status"] == "ACTIVE"


# ─────────── Difficulty: FraudHold OPEN -> {CLEARED, CONFIRMED} branch ───────────

def _two_held_cards():
    """Two ACTIVE cards loaded 100000; card1 redeemed 20000 (balance 80000), card2
    redeemed 30000 (balance 70000); a hold opened (analyst-1) on each."""
    _merchant, _program, _batch, cards = setup_multi_active_cards(2, 100000)
    c1, c2 = cards[0], cards[1]
    redeem(c1["id"], 20000)
    redeem(c2["id"], 30000)
    h1 = open_hold(c1["id"], reason="MANUAL", analyst_id="analyst-1")
    h2 = open_hold(c2["id"], reason="CHARGEBACK", analyst_id="analyst-1")
    return c1, c2, h1, h2


def test_clear_branch_keeps_redemption_and_reactivates(api):
    """PRD §3.5: "**Clearing** (the benign branch) is permitted only while the hold is `OPEN` (else `ERR_INVALID_STATE`); it records the acting analyst's `X-User-ID` as `resolved_by_user_id`, moves the hold to the terminal `CLEARED` state, and unfreezes the card by returning it from `SUSPENDED` to `ACTIVE` with no change to the ledger."

    Design: Difficulty/non_linear_state_machine/fraudhold_open_branch_clear_vs_confirm
    """
    c1, _c2, h1, _h2 = _two_held_cards()
    cleared = validate_success(
        api.clear_fraud_hold(h1["id"], make_fraud_analyst_headers("analyst-1")), 200)
    assert cleared["status"] == "CLEARED"
    card1 = validate_success(api.get_gift_card(c1["id"], ANY), 200)
    assert card1["status"] == "ACTIVE"
    assert card1["balance_cents"] == 80000  # redemption left POSTED (no ledger change)


def test_confirm_branch_reverses_redemption_and_holds_suspended(api):
    """PRD §3.5: "On confirm the system records `resolved_by_user_id`, moves the hold to the terminal `CONFIRMED` state, and — this is the material effect — flips every `POSTED` `REDEMPTION` entry on the card to `REVERSED`, which restores the reversed value to the card's balance; the card itself stays `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/fraudhold_open_branch_clear_vs_confirm
    """
    _c1, c2, _h1, h2 = _two_held_cards()
    confirmed = validate_success(api.confirm_fraud_hold(h2["id"], ANALYST_2), 200)
    assert confirmed["status"] == "CONFIRMED"
    card2 = validate_success(api.get_gift_card(c2["id"], ANY), 200)
    assert card2["status"] == "SUSPENDED"
    assert card2["balance_cents"] == 100000  # 30000 redemption reversed


# ─────────── Difficulty: card balance conserved across redeem+reverse ───────────

def test_confirm_restores_balance_to_preredeem_load(api):
    """PRD §3.5: "On confirm the system records `resolved_by_user_id`, moves the hold to the terminal `CONFIRMED` state, and — this is the material effect — flips every `POSTED` `REDEMPTION` entry on the card to `REVERSED`, which restores the reversed value to the card's balance; the card itself stays `SUSPENDED`."

    Design: Difficulty/compensating_invariant/card_balance_conserved_redeem_reverse
    """
    _merchant, _program, _card, hold = setup_active_card_with_open_hold(
        100000, reason="CHARGEBACK", redeem_amount=20000)
    validate_success(api.confirm_fraud_hold(hold["id"], ANALYST_2), 200)
    card = validate_success(api.get_gift_card(_card["id"], ANY), 200)
    assert card["balance_cents"] == 100000


def test_balance_drops_on_redeem_then_restores_on_confirm(api):
    """PRD §3.5: "On confirm the system records `resolved_by_user_id`, moves the hold to the terminal `CONFIRMED` state, and — this is the material effect — flips every `POSTED` `REDEMPTION` entry on the card to `REVERSED`, which restores the reversed value to the card's balance; the card itself stays `SUSPENDED`."

    Design: Difficulty/compensating_invariant/card_balance_conserved_redeem_reverse
    """
    _merchant, _program, card, hold = setup_active_card_with_open_hold(
        100000, reason="CHARGEBACK", redeem_amount=20000)
    assert card["balance_cents"] == 80000  # after the 20000 redemption, before confirm
    validate_success(api.confirm_fraud_hold(hold["id"], ANALYST_2), 200)
    restored = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert restored["balance_cents"] == 100000


# ─────────── Difficulty: confirm -> settlement + merchant cascade ───────────

def test_confirm_restores_card_balance_in_settlement_cascade(api):
    """PRD §3.5: "On confirm the system records `resolved_by_user_id`, moves the hold to the terminal `CONFIRMED` state, and — this is the material effect — flips every `POSTED` `REDEMPTION` entry on the card to `REVERSED`, which restores the reversed value to the card's balance; the card itself stays `SUSPENDED`."

    Design: Difficulty/transitive_cascade/fraud_confirm_reversal_settlement_cascade
    """
    _merchant, _program, card, _settlement, hold = setup_settlement_cascade_pending_confirm(
        unit_load_cents=100000, redeem_amount=20000)
    validate_success(api.confirm_fraud_hold(hold["id"], ANALYST_2), 200)
    card_after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert card_after["balance_cents"] == 100000


def test_confirm_removes_reversed_entry_from_open_batch_and_merchant(api):
    """PRD §3.5: "a reversed entry carrying a `settlement_batch_id` of a batch still in `OPEN` status is removed from that batch, which triggers the batch to recompute its `gross_redemptions_cents` and `net_payout_cents`; a reversed entry whose `settlement_batch_id` is null instead drives a recompute of the owning `Merchant`'s `unsettled_redemptions_cents`."

    Design: Difficulty/transitive_cascade/fraud_confirm_reversal_settlement_cascade
    """
    merchant, _program, _card, settlement, hold = setup_settlement_cascade_pending_confirm(
        unit_load_cents=100000, redeem_amount=20000)
    validate_success(api.confirm_fraud_hold(hold["id"], ANALYST_2), 200)
    batch_after = validate_success(api.get_settlement_batch(settlement["id"], ANY), 200)
    assert batch_after["gross_redemptions_cents"] == 0
    assert batch_after["net_payout_cents"] == 0
    merchant_after = validate_success(api.get_merchant(merchant["id"], ANY), 200)
    assert merchant_after["unsettled_redemptions_cents"] == 0


# ─────────── Corner: segregation of duties on confirm ───────────

def test_confirm_by_opening_analyst_rejected(api):
    """PRD §2.10: "Confirming a fraud hold requires that `X-User-ID` differ from the hold's `opened_by_user_id`; finalizing a settlement batch requires that `X-User-ID` differ from the batch's `opened_by_user_id`. In either case a match — the same operator attempting both sides — is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/rbac/fraud_confirm_same_analyst_returns_sod
    """
    _merchant, _program, _card, hold = setup_active_card_with_open_hold(
        5000, reason="MANUAL", analyst_id="analyst-1")
    res = api.confirm_fraud_hold(hold["id"], make_fraud_analyst_headers("analyst-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
