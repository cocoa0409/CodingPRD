"""Calculations: reload bonus, dormancy fee floor, and order-sensitive split-tender legs.

Queue B (Corner) section calculations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    setup_active_campaign_and_card, setup_card_for_dormancy,
    setup_draft_redemption_over_cards, settle_redemption,
    reload_card_payload,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]


def test_reload_bonus_credited_during_active_campaign(api):
    """PRD §3.3: "If a PromoCampaign in the same program is ACTIVE at the instant of the
    reload, the system additionally posts a BONUS credit equal to the reload amount multiplied
    by that campaign's bonus_pct, rounded half up to whole cents."

    Design: Corner/calculations/reload_bonus_credited_during_active_campaign
    """
    program, campaign, card = setup_active_campaign_and_card(
        settled_cents=2000, window_start="2026-01-01T00:00:00Z",
        window_end="2026-03-01T00:00:00Z", sync_at_iso="2026-02-01T00:00:00Z",
        bonus_pct=0.10)
    assert campaign["status"] == "ACTIVE"
    validate_success(api.reload_card(card["id"], reload_card_payload(5000), _STORE), 200)
    after = validate_success(api.get_card(card["id"], _STORE), 200)
    # 2000 + RELOAD 5000 + BONUS round_half_up(5000 * 0.10) = 2000 + 5000 + 500 = 7500.
    assert after["settled_balance_cents"] == 7500


def test_dormancy_fee_is_capped_by_balance_floor(api):
    """PRD §3.8: "the system charges a dormancy fee: a DORMANCY_FEE debit equal to the smaller
    of a fixed fee of 200 cents (two dollars) and the card's settled_balance_cents — so the
    fee can never drive the balance below zero."

    Design: Corner/calculations/dormancy_fee_min_with_balance_floor
    """
    program, state_rule, card = setup_card_for_dormancy(
        state_rule_kwargs={"expiration_allowed": False, "dormancy_fee_allowed": True,
                           "breakage_policy": "RECOGNIZE", "dormancy_threshold_months": 12},
        activate_at_iso="2025-01-01T00:00:00Z",
        assess_at_iso="2026-02-01T00:00:00Z",
        settled_cents=1500)
    get_success_data(api.assess_dormancy(card["id"], _ADMIN))
    after = validate_success(api.get_card(card["id"], _ADMIN), 200)
    # min(200, 1500) = 200 charged; 1500 - 200 = 1300; card stays ACTIVE (expiration off).
    assert after["settled_balance_cents"] == 1300
    assert after["lifecycle_status"] == "ACTIVE"


def test_split_tender_order_reversed_changes_legs(api):
    """PRD §3.5: "Because allocation follows the pinned order, the same set of cards in a
    different card_id_order yields different per-card leg_amount_cents and drives a different
    set of cards to EXHAUSTED."

    Design: Corner/calculations/split_tender_order_reversed_changes_legs
    """
    # Same cards A=3000, B=1500, C=4000; demand 5000 in order [C, B, A].
    program, cards, redemption = setup_draft_redemption_over_cards(
        requested_amount_cents=5000, balances=[3000, 1500, 4000], order_index=[2, 1, 0])
    validate_success(settle_redemption(redemption["id"], redemption["version"]), 200)
    a = validate_success(api.get_card(cards[0]["id"], _STORE), 200)
    b = validate_success(api.get_card(cards[1]["id"], _STORE), 200)
    c = validate_success(api.get_card(cards[2]["id"], _STORE), 200)
    # C draws 4000, B draws 1000 (→500 left), A untouched.
    assert c["settled_balance_cents"] == 0
    assert b["settled_balance_cents"] == 500
    assert a["settled_balance_cents"] == 3000
