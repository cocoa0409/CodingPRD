"""Combinatorial formulas: split-tender waterfall allocation and per-card B2B pricing.

Queue A (Difficulty) rule combinatorial_formula.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_draft_redemption_over_cards, settle_redemption, setup_quoted_bulk_order,
    make_b2b_buyer_headers,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]


def test_waterfall_allocates_in_pinned_order(api):
    """PRD §3.5: "The allocation itself is a strict waterfall over card_id_order in exactly
    the given order — the client-pinned order is the allocation order."
    PRD §3.5: "For each card in order it takes the smaller of the remaining amount and that
    card's available balance (treating any negative available balance as zero); if that take
    is greater than zero it creates one RedemptionLeg ... and subtracts the take from the
    remaining amount."

    Design: Difficulty/combinatorial_formula/split_tender_waterfall_order_sensitive
    """
    program, cards, redemption = setup_draft_redemption_over_cards(
        requested_amount_cents=5000, balances=[3000, 1500, 4000], order_index=[0, 1, 2])
    settled = validate_success(
        settle_redemption(redemption["id"], redemption["version"]), 200)
    assert settled["status"] == "SETTLED"
    assert settled["allocated_amount_cents"] == 5000
    # Demand 5000 over [A=3000, B=1500, C=4000]: A→0, B→0, C draws 500 (4000-500=3500).
    a = validate_success(api.get_card(cards[0]["id"], _STORE), 200)
    b = validate_success(api.get_card(cards[1]["id"], _STORE), 200)
    c = validate_success(api.get_card(cards[2]["id"], _STORE), 200)
    assert a["settled_balance_cents"] == 0
    assert b["settled_balance_cents"] == 0
    assert c["settled_balance_cents"] == 3500


def test_waterfall_stops_once_demand_met(api):
    """PRD §3.5: "Allocation stops as soon as the remaining amount reaches zero."
    PRD §3.5: "Cards that would draw zero produce no leg."

    Design: Difficulty/combinatorial_formula/split_tender_waterfall_order_sensitive
    """
    # Demand 3000 fully covered by the first card; later cards draw nothing.
    program, cards, redemption = setup_draft_redemption_over_cards(
        requested_amount_cents=3000, balances=[3000, 1500, 4000], order_index=[0, 1, 2])
    settled = validate_success(
        settle_redemption(redemption["id"], redemption["version"]), 200)
    assert settled["allocated_amount_cents"] == 3000
    a = validate_success(api.get_card(cards[0]["id"], _STORE), 200)
    b = validate_success(api.get_card(cards[1]["id"], _STORE), 200)
    c = validate_success(api.get_card(cards[2]["id"], _STORE), 200)
    assert a["settled_balance_cents"] == 0
    assert b["settled_balance_cents"] == 1500, "B untouched once demand met"
    assert c["settled_balance_cents"] == 4000, "C untouched once demand met"
    legs, _ = _list_legs(api, redemption["id"])
    assert len(legs) == 1, "only the drawn card produces a leg"


def test_bulk_pricing_rounds_per_card_then_multiplies(api):
    """PRD §3.9: "first compute one card's discounted price as face_value_cents multiplied by
    the quantity one minus the program's b2b_discount_pct, rounded half up to whole cents;
    then multiply that per-card price by card_count. The rounding is applied per card before
    the multiplication — rounding each card's price first and only then multiplying — which
    can differ from rounding a summed total by as much as one cent per card less one."

    Design: Difficulty/combinatorial_formula/bulk_order_round_per_card_then_multiply
    """
    program, buyer, bulk_order = setup_quoted_bulk_order(
        card_count=7, face_value_cents=2500, b2b_discount_pct=0.035)
    confirmed = validate_success(
        api.confirm_bulk_order(bulk_order["id"], make_b2b_buyer_headers(buyer["id"])), 200)
    assert confirmed["status"] == "CONFIRMED"
    # per_card = round_half_up(2500 * (1 - 0.035)) = round_half_up(2412.5) = 2413;
    # net = 2413 * 7 = 16891 (sum-then-round would give 16888).
    assert confirmed["net_invoice_cents"] == 16891


def test_bulk_pricing_single_card_per_card_rounding(api):
    """PRD §3.9: "first compute one card's discounted price as face_value_cents multiplied by
    the quantity one minus the program's b2b_discount_pct, rounded half up to whole cents;
    then multiply that per-card price by card_count."

    Design: Difficulty/combinatorial_formula/bulk_order_round_per_card_then_multiply
    """
    program, buyer, bulk_order = setup_quoted_bulk_order(
        card_count=1, face_value_cents=2500, b2b_discount_pct=0.035)
    confirmed = validate_success(
        api.confirm_bulk_order(bulk_order["id"], make_b2b_buyer_headers(buyer["id"])), 200)
    # per_card = round_half_up(2412.5) = 2413; net = 2413 * 1 = 2413.
    assert confirmed["net_invoice_cents"] == 2413


def _list_legs(api, redemption_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api.list_redemption_legs(_STORE, params={"redemption_id": redemption_id})
    try:
        return validate_paginated(resp)
    except AssertionError:
        body = resp.json()
        return body["data"], body.get("meta", {})
