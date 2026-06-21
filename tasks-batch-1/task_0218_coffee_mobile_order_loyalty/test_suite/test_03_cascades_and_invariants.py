"""Cascading side effects of pay/cancel/refund and conservation invariants.

Queue A (Difficulty): transitive_cascade, compensating_invariant.
Queue B (Corner): calculations (card_balance, auto-reload),
                  cross_cutting_complexity_layers (derived_card_balance_after_spend).
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    validate_success,
)


# ─── transitive_cascade ───────────────────────────────────────────────────

def test_cancel_cascades_refund_wallet_card_balance(api):
    """PRD §3.8: "Cancelling advances `fulfillment_status` from `PLACED` to
    `CANCELLED` and triggers a full compensation: a `Refund` to the stored-value
    wallet is auto-created, the order's `payment_status` moves from `PAID` to
    `REFUNDED`, a `WalletTransaction` of kind `REFUND` carrying the positive
    `total_cents` is appended and the card's `balance_cents` recomputed".
    PRD §3.8: "whose `amount_cents` equals the order's `total_cents`".

    Card funded 5000, paid STORED_VALUE (total 669 -> balance 4331), placed, then
    cancelled: card balance returns to 5000, payment_status REFUNDED, the Refund
    records amount_cents 669.

    Design: Difficulty/transitive_cascade/cancel_depth3_refund_wallettxn_cardbalance
    """
    ctx = fx.setup_placed_order(item_price=615, pay_method="STORED_VALUE", card_balance=5000)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    cancelled = validate_success(api.cancel_order(mid, ctx["order"]["id"], hdr))
    assert cancelled["payment_status"] == "REFUNDED", cancelled

    card = fx.get_card(mid)
    assert card["balance_cents"] == 5000, card
    refunds, _ = _list(api, api.list_refunds, hdr, {"order_id": ctx["order"]["id"]})
    assert len(refunds) == 1, refunds
    assert refunds[0]["amount_cents"] == 669, refunds[0]


def test_cancel_appends_refund_wallet_transaction(api):
    """PRD §3.8: "a `WalletTransaction` of kind `REFUND` carrying the positive
    `total_cents` is appended and the card's `balance_cents` recomputed".
    PRD §3.1: "Wallet transactions can be listed (filterable by `card_id` for a card's
    history or by `order_id` for the events tied to a particular order)".

    The middle link of the cancel cascade: after cancelling the STORED_VALUE order
    (total 669), the order's wallet history contains a REFUND transaction of
    +669 cents.

    Design: Difficulty/transitive_cascade/cancel_depth3_refund_wallettxn_cardbalance
    """
    ctx = fx.setup_placed_order(item_price=615, pay_method="STORED_VALUE", card_balance=5000)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    validate_success(api.cancel_order(mid, ctx["order"]["id"], hdr))
    txns, _ = _list(api, api.list_wallet_transactions, hdr, {"order_id": ctx["order"]["id"]})
    refund_txns = [t for t in txns if t["kind"] == "REFUND"]
    assert len(refund_txns) == 1, txns
    assert refund_txns[0]["amount_cents"] == 669, refund_txns[0]


def test_pay_cascades_star_earn_lifetime_tier(api):
    """PRD §3.5: "computes `stars_earned` and appends a `StarLedgerEntry` of kind
    `EARN` carrying the positive `stars_earned` (after which the member's
    `star_balance`, `lifetime_stars`, and `tier` are re-derived — a member crossing
    the gold threshold moves from `GREEN` to `GOLD`)."
    PRD §2.5: "The member's `tier` is `GOLD` when `lifetime_stars` is at least the gold
    threshold of 200, and `GREEN` otherwise."

    A GREEN member pays a $200-pretax order EXTERNAL_CARD (earns 200 stars):
    stars_earned 200, lifetime_stars 200, tier re-derived to GOLD.

    Design: Difficulty/transitive_cascade/pay_depth3_starearn_lifetime_tier
    """
    ctx = fx.setup_base(item_price=20000, item_reward_eligible=False, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    # The base item is already 20000c (=$200 pretax). Order it.
    order = fx.create_cart_order(mid, store_id, ctx["slots"][0]["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    paid = validate_success(api.pay_order(mid, order["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["stars_earned"] == 200, paid
    member = validate_success(api.get_member(mid, hdr))
    assert member["lifetime_stars"] == 200, member
    assert member["tier"] == "GOLD", member


def test_pay_appends_star_ledger_earn_entry(api):
    """PRD §3.5: "computes `stars_earned` and appends a `StarLedgerEntry` of kind
    `EARN` carrying the positive `stars_earned`".
    PRD §2.5: "The `star_balance` is the sum of `delta_stars` across all of that
    member's ledger entries regardless of kind."

    After paying a 615c latte (6 stars), the member's star_balance is 6 — the
    projection of the appended EARN entry.

    Design: Difficulty/transitive_cascade/pay_depth3_starearn_lifetime_tier
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    fx.pay(mid, ctx["order"]["id"], "EXTERNAL_CARD")
    member = validate_success(api.get_member(mid, hdr))
    assert member["star_balance"] == 6, member
    assert member["lifetime_stars"] == 6, member


# ─── compensating_invariant ───────────────────────────────────────────────

def test_refund_preserves_card_balance_invariant(api):
    """PRD §3.8: "The conservation guarantee holds: after a pay-then-refund the card's
    `balance_cents` returns to its pre-pay value and the member's `star_balance`
    returns to its pre-pay value."
    PRD §2.5: "A `StoredValueCard`'s `balance_cents` is the sum of the `amount_cents`
    of every `WalletTransaction` whose `card_id` is the card, replayed in `created_at`
    order."

    Card reloaded to 5000, paid STORED_VALUE (ORDER_SPEND -669), placed, cancelled
    (REFUND +669): balance_cents returns to exactly 5000.

    Design: Difficulty/compensating_invariant/refund_preserves_card_balance_invariant
    """
    ctx = fx.setup_placed_order(item_price=615, pay_method="STORED_VALUE", card_balance=5000)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    cancelled = validate_success(api.cancel_order(mid, ctx["order"]["id"], hdr))
    assert cancelled["payment_status"] == "REFUNDED", cancelled
    card = fx.get_card(mid)
    assert card["balance_cents"] == 5000, card


def test_operator_refund_preserves_card_balance_invariant(api):
    """PRD §3.8: "When the `destination` is `STORED_VALUE`, or when the original pay
    method was the wallet, a `WalletTransaction` of kind `REFUND` carrying the positive
    `total_cents` is appended and the card's `balance_cents` recomputed".
    PRD §3.8: "The conservation guarantee holds: after a pay-then-refund the card's
    `balance_cents` returns to its pre-pay value and the member's `star_balance`
    returns to its pre-pay value."

    The operator-refund producing endpoint (not member cancel) also conserves the card
    balance: card 5000, STORED_VALUE pay (ORDER_SPEND -669), placed, then operator
    refund to STORED_VALUE (REFUND +669) -> balance_cents back to 5000.

    Design: Difficulty/compensating_invariant/refund_preserves_card_balance_invariant
    """
    ctx = fx.setup_placed_order(item_price=615, pay_method="STORED_VALUE", card_balance=5000)
    mid = ctx["member"]["id"]
    refund = validate_success(api.refund_order(
        ctx["store"]["id"], ctx["order"]["id"],
        f.refund_payload("STORED_VALUE"), fx.OPERATOR), 201)
    assert refund["amount_cents"] == 669, refund
    card = fx.get_card(mid)
    assert card["balance_cents"] == 5000, card


def test_refund_preserves_star_balance_invariant(api):
    """PRD §3.8: "a `StarLedgerEntry` of kind `REVERSAL` carrying the negative of the
    order's `stars_earned` is appended (after which the member's `star_balance`,
    `lifetime_stars`, and `tier` are re-derived)".
    PRD §3.8: "after a pay-then-refund the card's `balance_cents` returns to its
    pre-pay value and the member's `star_balance` returns to its pre-pay value."

    A member with star_balance 0 pays EXTERNAL_CARD (earns 6), places, then cancels:
    the REVERSAL(-6) restores star_balance to 0.

    Design: Difficulty/compensating_invariant/refund_preserves_member_star_balance_invariant
    """
    ctx = fx.setup_placed_order(item_price=615, pay_method="EXTERNAL_CARD")
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    assert ctx["order"]["stars_earned"] == 6, ctx["order"]
    cancelled = validate_success(api.cancel_order(mid, ctx["order"]["id"], hdr))
    assert cancelled["payment_status"] == "REFUNDED", cancelled
    member = validate_success(api.get_member(mid, hdr))
    assert member["star_balance"] == 0, member


def test_operator_refund_preserves_star_balance_invariant(api):
    """PRD §3.8: "A `StarLedgerEntry` of kind `REVERSAL` carrying the negative of the
    order's `stars_earned` is appended and the member's `star_balance`,
    `lifetime_stars`, and `tier` are re-derived."
    PRD §3.8: "after a pay-then-refund the card's `balance_cents` returns to its
    pre-pay value and the member's `star_balance` returns to its pre-pay value."

    The operator-refund producing endpoint also conserves the star balance: a member
    with star_balance 0 pays EXTERNAL_CARD (EARN +6), places, then an operator refund
    appends REVERSAL(-6) -> star_balance back to 0.

    Design: Difficulty/compensating_invariant/refund_preserves_member_star_balance_invariant
    """
    ctx = fx.setup_placed_order(item_price=615, pay_method="EXTERNAL_CARD")
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    assert ctx["order"]["stars_earned"] == 6, ctx["order"]
    refund = validate_success(api.refund_order(
        ctx["store"]["id"], ctx["order"]["id"],
        f.refund_payload("ORIGINAL_METHOD"), fx.OPERATOR), 201)
    assert refund["stars_reversed"] == 6, refund
    member = validate_success(api.get_member(mid, hdr))
    assert member["star_balance"] == 0, member


# ─── Queue B: card balance projection & auto-reload ───────────────────────

def test_card_balance_projection_after_reloads(api):
    """PRD §2.5: "A `StoredValueCard`'s `balance_cents` is the sum of the
    `amount_cents` of every `WalletTransaction` whose `card_id` is the card, replayed
    in `created_at` order."

    Two reloads 1500 + 2500 -> balance_cents 4000.

    Design: Corner/calculations/card_balance_projection_after_reloads
    """
    member = fx.create_member()
    mid = member["id"]
    fx.reload_card(mid, 1500)
    fx.reload_card(mid, 2500)
    card = fx.get_card(mid)
    assert card["balance_cents"] == 4000, card


def test_derived_card_balance_after_stored_value_spend(api):
    """PRD §3.5: "a `WalletTransaction` of kind `ORDER_SPEND` carrying the negative
    `total_cents` is appended, the card's `balance_cents` is recomputed".
    PRD §2.5: "an order spend contributes a negative `amount_cents`. The resulting
    `balance_cents` must never be negative."

    Card funded 5000, STORED_VALUE pay of total 669 -> balance reconciles to 4331.

    Design: Corner/cross_cutting_complexity_layers/derived_card_balance_after_spend
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    card = fx.reload_card(mid, 5000)
    validate_success(api.pay_order(
        mid, ctx["order"]["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=card["version"]), hdr))
    after = fx.get_card(mid)
    assert after["balance_cents"] == 4331, after


def test_auto_reload_fires_at_pay_when_below_threshold(api):
    """PRD §3.5: "If `pay_method` is `STORED_VALUE`, auto-reload is enabled on the
    card, the card's `balance_cents` is at or below `auto_reload_threshold_cents`, and
    the balance is also below `total_cents`, then an auto-reload fires: a
    `WalletTransaction` of kind `AUTO_RELOAD` carrying the card's
    `auto_reload_amount_cents` is appended, `balance_cents` is recomputed".

    Card balance 500 (<= threshold 1000 and < total 669), auto-reload amount 2500
    -> AUTO_RELOAD fires; post-pay balance 500 + 2500 - 669 = 2331.

    Design: Corner/calculations/auto_reload_threshold_fires_at_pay
    """
    ctx = fx.setup_base(item_price=615, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    validate_success(api.update_member_card(
        mid, f.update_card_payload(auto_reload_enabled=True,
                                   auto_reload_threshold_cents=1000,
                                   auto_reload_amount_cents=2500), hdr))
    card = fx.reload_card(mid, 500)
    order = fx.create_cart_order(mid, store_id, ctx["slots"][0]["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    paid = validate_success(api.pay_order(
        mid, order["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=card["version"]), hdr))
    assert paid["payment_status"] == "PAID", paid
    after = fx.get_card(mid)
    assert after["balance_cents"] == 2331, after


# ─── helpers ──────────────────────────────────────────────────────────────

def _list(api, fn, headers, params):
    from test_helpers import validate_paginated
    return validate_paginated(fn(headers, params=params))
