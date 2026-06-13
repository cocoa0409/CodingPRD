"""Calculation engine — SCAFFOLD §1.3 / PRD §3.4-3.5.

Money is integer cents; stars are integers. The only rounding step is tax, computed
once on the post-discount taxable base with round-half-up.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from constants import (
    TAX_RATE_BPS,
    GREEN_STARS_PER_DOLLAR,
    GOLD_STARS_PER_DOLLAR,
    STORED_VALUE_BONUS_PER_DOLLAR,
)


def lines_for_order(order_id):
    """Order lines for an order, sorted by created_at then sequence (deterministic)."""
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


def compute_line_pricing(menu_item, modifiers, quantity, options_by_id):
    """unit_price_cents = base_price + sum(option.price_delta * count);
    line_total_cents = unit_price * quantity."""
    unit_price = menu_item["base_price_cents"]
    for sel in modifiers:
        opt = options_by_id[sel["modifier_option_id"]]
        unit_price += opt["price_delta_cents"] * sel["count"]
    line_total = unit_price * quantity
    return unit_price, line_total


def round_half_up_div(numerator, denominator):
    """Integer round-half-up of numerator/denominator."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def compute_order_total(order, reward):
    """Pinned evaluation order (PRD §3.5). Returns a dict with subtotal_cents,
    reward_discount_cents, tax_cents, total_cents, and the redeemed line id (or None).

    `reward` is the RewardGrant dict or None. Caller has already validated reward
    applicability when reward is provided.
    """
    lines = lines_for_order(order["id"])

    # 1. subtotal = sum of line_total over ALL lines at full price
    subtotal = sum(l["line_total_cents"] for l in lines)

    # 2. reward_discount
    reward_discount = 0
    redeemed_line_id = None
    if reward is not None:
        eligible = [
            l for l in lines
            if db.menu_items[l["menu_item_id"]]["reward_eligible"]
        ]
        # caller guarantees eligible is non-empty (else ERR_REWARD_NOT_APPLICABLE)
        # cheapest eligible by unit_price, tie-break earliest created_at
        eligible.sort(key=lambda l: (l["unit_price_cents"], l["created_at"], l["_seq"]))
        cheapest = eligible[0]
        reward_discount = min(cheapest["unit_price_cents"], reward["max_discount_cents"])
        redeemed_line_id = cheapest["id"]

    # 3. taxable base
    taxable_base = subtotal - reward_discount

    # 4. tax: once, post-discount, round-half-up
    tax = round_half_up_div(taxable_base * TAX_RATE_BPS, 10000)

    # 5. total
    total = subtotal - reward_discount + tax

    return {
        "subtotal_cents": subtotal,
        "reward_discount_cents": reward_discount,
        "tax_cents": tax,
        "total_cents": total,
        "redeemed_line_id": redeemed_line_id,
    }


def compute_stars_earned(tier, pay_method, total_cents, tax_cents):
    """SCAFFOLD §1.3 stars_earned. Stars accrue on pre-tax spend only; floor to dollars."""
    base_rate = GOLD_STARS_PER_DOLLAR if tier == "GOLD" else GREEN_STARS_PER_DOLLAR
    method_bonus = STORED_VALUE_BONUS_PER_DOLLAR if pay_method == "STORED_VALUE" else 0
    pre_tax = total_cents - tax_cents
    eligible_dollars = pre_tax // 100  # floor
    if eligible_dollars < 0:
        eligible_dollars = 0
    return eligible_dollars * (base_rate + method_bonus)
