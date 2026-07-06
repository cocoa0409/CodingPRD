"""Calculation rules from SCAFFOLD Table 1.3 / PRD §3."""
from decimal import Decimal

from core import (
    db, round_half_up, MARKDOWN_PCT, REWARD_VALUE_CENTS, PUNCHES_PER_REWARD,
    CATERING_DEPOSIT_THRESHOLD_CENTS, DEPOSIT_PCT,
)


def markdown_price(product):
    # round_half_up(unit_price_cents * (1 - MARKDOWN_PCT))
    return round_half_up(Decimal(product["unit_price_cents"]) * (Decimal(1) - MARKDOWN_PCT))


def line_price(product, qty, marked_down):
    """Tiered per-line price (integer cents). Pinned eval order."""
    if marked_down:
        return qty * markdown_price(product)
    threshold = product["bulk_threshold"]
    if qty >= threshold:
        return qty * product["bulk_unit_price_cents"]
    dozens = qty // 12
    rem = qty % 12
    return dozens * product["dozen_price_cents"] + rem * product["unit_price_cents"]


def lines_subtotal(line_items):
    """Sum of line_price over {product_id, qty, marked_down?} items (no discount)."""
    total = 0
    for li in line_items:
        product = db.products[li["product_id"]]
        total += line_price(product, li["qty"], li.get("marked_down", False))
    return total


def wholesale_delivery_amount(line_items, discount_pct):
    """Sum-then-round once. line_items priced with no markdown."""
    raw = 0
    for li in line_items:
        product = db.products[li["product_id"]]
        raw += line_price(product, li["qty"], False)
    return round_half_up(Decimal(raw) * (Decimal(1) - Decimal(str(discount_pct))))


def preorder_deposit(subtotal_cents):
    if subtotal_cents >= CATERING_DEPOSIT_THRESHOLD_CENTS:
        return round_half_up(Decimal(subtotal_cents) * DEPOSIT_PCT)
    return 0


def apply_loyalty_accrual(account, total_qty):
    """Accrue punches; auto-convert. Returns number of conversions performed."""
    earned = total_qty // 12
    account["punch_count"] += earned
    conversions = 0
    while account["punch_count"] >= PUNCHES_PER_REWARD:
        account["punch_count"] -= PUNCHES_PER_REWARD
        account["reward_balance_cents"] += REWARD_VALUE_CENTS
        conversions += 1
    return earned, conversions


def reverse_loyalty_accrual(account, earned, conversions):
    """Exact inverse of apply_loyalty_accrual."""
    account["reward_balance_cents"] -= conversions * REWARD_VALUE_CENTS
    account["punch_count"] += conversions * PUNCHES_PER_REWARD
    account["punch_count"] -= earned
