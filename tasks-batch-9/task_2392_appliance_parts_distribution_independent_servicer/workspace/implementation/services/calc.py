"""Pure calculation helpers and every named constant (SCAFFOLD 1.3 / PRD 2.5)."""

from decimal import Decimal, ROUND_HALF_UP

# supersession_chain_resolution
MAX_SUPERSESSION_HOPS = 5

# order_line_pricing
VOLUME_DISCOUNT_PCT = Decimal("0.02")
VOLUME_DISCOUNT_MIN_QTY = 10
MAX_DISCOUNT_PCT = Decimal("0.45")

# freight_assessment
OVERNIGHT_BASE_CENTS = 1495
WEIGHT_BLOCK_GRAMS = 5000
WEIGHT_BLOCK_CENTS = 250
LATE_CUTOFF_SURCHARGE_CENTS = 500
FREE_FREIGHT_SUBTOTAL_CENTS = 50000

# servicer_credit_exposure
CREDIT_HOLD_RELEASE_RATIO = Decimal("0.90")

# restocking_fee_and_credit
RESTOCK_FEE_PCT_TIER1 = Decimal("0.10")
RESTOCK_TIER1_MAX_DAYS = 15
RESTOCK_FEE_PCT_TIER2 = Decimal("0.20")
LARGE_RETURN_GROSS_CENTS = 100000
LARGE_RETURN_FEE_ADDER_PCT = Decimal("0.05")

# return_window_days
RETURN_WINDOW_DAYS = 30
CORE_RETURN_WINDOW_DAYS = 60

# servicer_delinquency_score
DELINQUENCY_BASE_SCORE = 80
DELINQUENCY_OVERDUE_PENALTY = 15
DELINQUENCY_DENIED_CLAIM_PENALTY = 20
DELINQUENCY_NLN_RETURN_PENALTY = 8
DELINQUENCY_CERT_BONUS_PER = 5
DELINQUENCY_CERT_BONUS_CAP = 15
DELINQUENCY_HOLD_THRESHOLD = 40
DELINQUENCY_ROLLING_WINDOW_DAYS = 180

# pricing_tier_assignment
TIER_LOOKBACK_DAYS = 365

# substitute_price_variance
SUBSTITUTE_VARIANCE_CAP_PCT = Decimal("0.25")

# warranty_claim_amount
WARRANTY_CLAIM_WINDOW_DAYS = 90
MAX_RESUBMISSIONS = 2

CREDIT_TERM_DAYS = {"PREPAY": 0, "NET_15": 15, "NET_30": 30, "NET_45": 45}

CERT_RANK = {"NONE": 0, "BASIC": 1, "ADVANCED": 2, "SEALED_SYSTEM": 3}

CATEGORY_DISCOUNT_FIELD = {
    "ELECTRICAL": "discount_pct_electrical",
    "MECHANICAL": "discount_pct_mechanical",
    "COSMETIC": "discount_pct_cosmetic",
    "SEALED_SYSTEM": "discount_pct_sealed_system",
}


def round_half_up(value):
    """Round a Decimal to a whole integer, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def cert_level_required(part):
    if part["category"] == "SEALED_SYSTEM":
        return "SEALED_SYSTEM"
    if part["category"] == "ELECTRICAL":
        return "ADVANCED"
    return "NONE"


def is_returnable(part):
    return part["category"] != "ELECTRICAL" and part["lifecycle_status"] != "NLA"


def tier_discount(tier, category):
    return dec(tier[CATEGORY_DISCOUNT_FIELD[category]])


def unit_price_cents(part, tier, quantity):
    base = tier_discount(tier, part["category"])
    bonus = VOLUME_DISCOUNT_PCT if quantity >= VOLUME_DISCOUNT_MIN_QTY else Decimal(0)
    effective = base + bonus
    if effective > MAX_DISCOUNT_PCT:
        effective = MAX_DISCOUNT_PCT
    return round_half_up(dec(part["list_price_cents"]) * (Decimal(1) - effective))


def weight_block_cents(total_grams):
    blocks = -(-total_grams // WEIGHT_BLOCK_GRAMS)  # ceil
    return blocks * WEIGHT_BLOCK_CENTS


def price_variance_pct(obsolete_list, substitute_list):
    ratio = (dec(substitute_list) - dec(obsolete_list)) / dec(obsolete_list)
    return ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def restocking_figures(reason_code, days, gross_return_cents, fee_waived):
    """Returns (restocking_fee_pct, restocking_fee_cents, credit_amount_cents)."""
    if reason_code in ("DEFECTIVE_ON_ARRIVAL", "CORE_RETURN"):
        pct = Decimal("0.0")
    elif days <= RESTOCK_TIER1_MAX_DAYS:
        pct = RESTOCK_FEE_PCT_TIER1
    else:
        pct = RESTOCK_FEE_PCT_TIER2
    if gross_return_cents >= LARGE_RETURN_GROSS_CENTS and pct > 0:
        pct = pct + LARGE_RETURN_FEE_ADDER_PCT
    if fee_waived:
        pct = Decimal("0.0")
    fee = round_half_up(dec(gross_return_cents) * pct)
    credit = gross_return_cents - fee
    return pct, fee, credit


def hold_release_ceiling(credit_limit_cents):
    """floor(credit_limit_cents * CREDIT_HOLD_RELEASE_RATIO)."""
    return (credit_limit_cents * 90) // 100


def clamp_score(score):
    if score < 0:
        return 0
    if score > 100:
        return 100
    return score
