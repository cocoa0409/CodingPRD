"""Calculation rules (scaffold §1.3 / PRD §3). Integer cents; pinned rounding."""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

POINT_VALUE_CENTS = 5
GOLD_MULTIPLIER = 2
DEPOSIT_PCT = 30


def _floor_div(numer, denom):
    """Exact floor of numer/denom for non-negative integers."""
    return numer // denom


def line_discount(qty, unit_price_cents, discount_pct):
    """floor(qty * unit_price * pct / 100) — per-line floor (PRD §3.3)."""
    raw = qty * unit_price_cents * discount_pct
    return raw // 100


def special_order_deposit(requested_qty, quoted_unit_cost_cents):
    """ceil(requested_qty * quoted_unit_cost * 30 / 100) (PRD §3.7)."""
    raw = requested_qty * quoted_unit_cost_cents * DEPOSIT_PCT
    # ceiling division
    return -((-raw) // 100)


def loyalty_accrual(net_total_cents, base_rate, is_gold):
    """floor(net/100) dollars; rate = base * (2 if GOLD else 1); points = dollars*rate."""
    eligible_dollars = net_total_cents // 100
    rate = base_rate * (GOLD_MULTIPLIER if is_gold else 1)
    return eligible_dollars * rate


def warranty_payout(line_net_cents, line_qty, claim_qty, warranty_pct):
    """floor(claim_qty * (line_net/line_qty) * pct / 100), single final floor.

    effective_unit_net kept as exact rational (line_net/line_qty); multiply by
    claim_qty and pct, divide by 100, single floor at the very end (PRD §3.10).
    """
    # claim_qty * line_net / line_qty * pct / 100, floored once.
    numer = claim_qty * line_net_cents * warranty_pct
    denom = line_qty * 100
    return numer // denom
