"""Calculation primitives (PRD §2.8 / §3.3 / §3.5 / §3.7 / §3.9 / §3.10)."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_int(value):
    """Round Decimal/float to integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dp(value, dp):
    """Round Decimal/float to a fixed number of decimal places, half-up. Returns float."""
    quant = Decimal(10) ** -dp
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


# --------------------- Discount-tier selection ----------------------

def select_discount_tier(participant_count, discount_tiers):
    """Return (settled_tier_index, settled_discount_basis_points)."""
    qualifying = [(i, t) for i, t in enumerate(discount_tiers)
                  if t["min_participants"] <= participant_count]
    if not qualifying:
        return None, 0
    idx, tier = qualifying[-1]  # tiers ordered ascending, last qualifying = largest min_participants
    return idx, tier["discount_basis_points"]


# --------------------- Order total ----------------------

def compute_order_total(subtotal_cents, discount_bp):
    """floor truncation on the discount step; total floored at zero."""
    discount_amount = (subtotal_cents * discount_bp) // 10000
    total = subtotal_cents - discount_amount
    if total < 0:
        total = 0
    return total


# --------------------- Tiered rebate ----------------------

PRIMARY_RATE_BP_BY_TIER = {1: 800, 2: 500, 3: 300}
SECONDARY_BONUS_BP_BY_TIER = {1: 200, 2: 100}
UPSTREAM_RATE_BP_BY_DEPTH = {1: 150, 2: 50}
REBATE_CAP_BP = 1500


def compute_tiered_rebate(settled_total_cents, leader_role, primary_tier,
                          secondary_tier=None, upstream_depth=None):
    if leader_role == "PRIMARY":
        base = PRIMARY_RATE_BP_BY_TIER[primary_tier]
        bonus = SECONDARY_BONUS_BP_BY_TIER.get(secondary_tier, 0) if secondary_tier else 0
        gross_rate_bp = base + bonus
    elif leader_role == "SECONDARY":
        gross_rate_bp = SECONDARY_BONUS_BP_BY_TIER[secondary_tier]
    elif leader_role == "UPSTREAM":
        gross_rate_bp = UPSTREAM_RATE_BP_BY_DEPTH[upstream_depth]
    else:
        raise ValueError(f"unknown leader_role {leader_role}")
    capped = min(gross_rate_bp, REBATE_CAP_BP)
    gross_rebate_cents = (settled_total_cents * capped) // 10000
    return gross_rebate_cents


# --------------------- Tax withholding (per-line round, then sum) ----------------------

TAX_RATE_BP_PER_LINE = 700


def compute_tax_withholding(gross_rebate_cents, line_items):
    """Return tax_withholding_cents per the round-per-line-then-sum rule."""
    weights = [li["unit_price_cents"] * li["quantity"] for li in line_items]
    total_weight = sum(weights)
    if total_weight == 0:
        return 0
    n = len(line_items)
    per_line_gross = []
    running = 0
    for i in range(n):
        if i < n - 1:
            share = (gross_rebate_cents * weights[i]) // total_weight
            per_line_gross.append(share)
            running += share
        else:
            per_line_gross.append(gross_rebate_cents - running)
    per_line_with = []
    for g in per_line_gross:
        v = Decimal(g) * Decimal(TAX_RATE_BP_PER_LINE) / Decimal(10000)
        per_line_with.append(int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    return sum(per_line_with)


# --------------------- T+N payout schedule ----------------------

PAYOUT_LAG_BY_TIER = {1: 3, 2: 5, 3: 7}


def compute_payout_target(order_paid_period_index, primary_tier):
    return order_paid_period_index + PAYOUT_LAG_BY_TIER[primary_tier]


# --------------------- Shipment ETA ----------------------

def compute_shipment_eta(dispatched_period_index, warehouse, cold_chain_segment):
    if cold_chain_segment:
        return dispatched_period_index + warehouse.get("cold_handling_periods", 1)
    return dispatched_period_index + warehouse.get("handling_periods", 1)


# --------------------- Risk scores ----------------------

def chronic_risk_score(bot_count, fake_count, collusion_count):
    bot_d = Decimal(bot_count) / Decimal(30)
    fake_d = Decimal(fake_count) / Decimal(30)
    col_d = Decimal(collusion_count) / Decimal(30)
    raw = (Decimal("0.30") * bot_d + Decimal("0.40") * fake_d + Decimal("0.30") * col_d) * Decimal(100)
    capped = min(raw, Decimal(100))
    return round_half_up_dp(capped, 2)


def acute_risk_score(bot_count, fake_count, collusion_count):
    bot_d = Decimal(bot_count) / Decimal(5)
    fake_d = Decimal(fake_count) / Decimal(5)
    col_d = Decimal(collusion_count) / Decimal(5)
    raw = (Decimal("0.50") * bot_d + Decimal("0.30") * fake_d + Decimal("0.20") * col_d) * Decimal(100) * Decimal("1.5")
    capped = min(raw, Decimal(100))
    return round_half_up_dp(capped, 2)


# --------------------- Pickup load factor ----------------------

def load_factor(held, capacity):
    if capacity == 0:
        return 0.0
    return round_half_up_dp(Decimal(held) / Decimal(capacity), 2)


def load_state(factor):
    if factor < 0.75:
        return "HEALTHY"
    if factor < 1.00:
        return "ELEVATED"
    return "FULL"


# --------------------- Fairness flash allocation ----------------------

CUSTOMERS_PER_TIER = 100


def per_customer_cap(tier_caps, current_request_seq):
    tier_idx = current_request_seq // CUSTOMERS_PER_TIER
    if tier_idx >= len(tier_caps):
        tier_idx = len(tier_caps) - 1
    return tier_caps[tier_idx]["max_units"]
