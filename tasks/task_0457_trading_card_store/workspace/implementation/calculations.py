"""All calculation rules (PRD §3, scaffold §1.3).

Money is integer cents (PRD §2.6). Where a cent amount is multiplied by a rate
or basis-point fraction and the result is not whole, it is rounded half-up. The
exact point of rounding is load-bearing and specified per calculation.
"""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half-up (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- buylist_payout (PRD §3.2) -------------------------------------------
# rate 0.70 STORE_CREDIT, 0.50 CASH. Round per line first, then sum.
STORE_CREDIT_RATE = Decimal("0.70")
CASH_RATE = Decimal("0.50")


def buylist_line_payout(market_price_cents, quantity, payout_method):
    rate = STORE_CREDIT_RATE if payout_method == "STORE_CREDIT" else CASH_RATE
    base = Decimal(market_price_cents) * Decimal(quantity)
    return int((base * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- registration_fee (PRD §3.4) -----------------------------------------
# base = Event.entry_fee_cents; loyalty discount in bps by tier.
# PROVISIONAL: loyalty only. FINAL: + early-bird 1000bps if early; cap 2000bps.
LOYALTY_DISCOUNT_BPS = {"BRONZE": 0, "SILVER": 500, "GOLD": 1000}
EARLY_BIRD_BPS = 1000
EARLY_BIRD_LEAD_SECONDS = 86400
MAX_DISCOUNT_BPS = 2000


def registration_fee_provisional(entry_fee_cents, loyalty_tier):
    tier_disc = Decimal(LOYALTY_DISCOUNT_BPS[loyalty_tier]) / Decimal(10000)
    fee = Decimal(entry_fee_cents) * (Decimal(1) - tier_disc)
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def registration_fee_final(entry_fee_cents, loyalty_tier, is_early):
    tier_disc = Decimal(LOYALTY_DISCOUNT_BPS[loyalty_tier]) / Decimal(10000)
    eff = tier_disc + (Decimal(EARLY_BIRD_BPS) / Decimal(10000) if is_early else Decimal(0))
    cap = Decimal(MAX_DISCOUNT_BPS) / Decimal(10000)
    if eff > cap:
        eff = cap
    fee = Decimal(entry_fee_cents) * (Decimal(1) - eff)
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- preorder_priority (PRD §3.3) ----------------------------------------
TIER_POINTS = {"BRONZE": 0, "SILVER": 20, "GOLD": 40}
DEPOSIT_STEP_CENTS = 500
DEPOSIT_CAP_PTS = 30
RECENCY_BASE = 25
RECENCY_DECAY = 5


def preorder_priority(loyalty_tier, deposit_paid_cents, created_at_rank):
    tier_pts = TIER_POINTS[loyalty_tier]
    deposit_pts = min(DEPOSIT_CAP_PTS, deposit_paid_cents // DEPOSIT_STEP_CENTS)
    recency_pts = max(0, RECENCY_BASE - (created_at_rank - 1) * RECENCY_DECAY)
    return tier_pts + deposit_pts + recency_pts


# ---- consignment_payout (PRD §3.7) ---------------------------------------
# Round commission per unit first, then multiply net by quantity.
def consignment_payout(ask_price_cents, commission_rate_bps, quantity):
    commission_per_unit = (
        Decimal(ask_price_cents) * Decimal(commission_rate_bps) / Decimal(10000)
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    net_per_unit = Decimal(ask_price_cents) - commission_per_unit
    return int(net_per_unit * Decimal(quantity))


# ---- grading_fee (PRD §3.6) ----------------------------------------------
BASE_FEE_CENTS = 1500
VALUE_SURCHARGE_BPS = 100
TIER_MULT = {"ECONOMY": Decimal("1.0"), "STANDARD": Decimal("1.5"), "EXPRESS": Decimal("2.5")}


def grading_fee(declared_value_cents, service_tier):
    surcharge = (
        Decimal(declared_value_cents) * Decimal(VALUE_SURCHARGE_BPS) / Decimal(10000)
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    total = (Decimal(BASE_FEE_CENTS) + surcharge) * TIER_MULT[service_tier]
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- loyalty_tier (PRD §3.1) ---------------------------------------------
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 200000


def loyalty_tier(lifetime_spend_cents):
    if lifetime_spend_cents >= GOLD_THRESHOLD_CENTS:
        return "GOLD"
    if lifetime_spend_cents >= SILVER_THRESHOLD_CENTS:
        return "SILVER"
    return "BRONZE"
