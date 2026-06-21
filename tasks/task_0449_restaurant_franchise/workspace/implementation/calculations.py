"""Calculation rules (SCAFFOLD §1.3 / PRD §3.9, §3.7).

All monetary amounts are integer cents. Fractional cents resolve with
round-half-up (away from zero on a .5) unless a rule explicitly floors
(PRD §2.6). float is never used for money — Decimal everywhere.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# Royalty tier ceilings (SCAFFOLD §1.3 royalty.constants / PRD §3.9)
TIER1_CEILING_CENTS = 5000000   # $50,000
TIER2_CEILING_CENTS = 10000000  # $100,000

# Audit scoring constants (SCAFFOLD §1.3 audit_score / PRD §3.7)
W_FOOD = Decimal("0.40")
W_CLEAN = Decimal("0.25")
W_SERVICE = Decimal("0.20")
W_BRAND = Decimal("0.15")
CRITICAL_FOOD_SAFETY_FLOOR = 70
CRITICAL_FAIL_CAP = Decimal("59.0")
PASS_FLOOR = Decimal("90.0")
CONDITIONAL_FLOOR = Decimal("70.0")

# Transfer-fee constants (SCAFFOLD §1.3 transfer_fee / PRD §3.9)
FLAT_MIN_CENTS = 1000000   # $10,000 floor
TRAINING_FEE_CENTS = 500000  # $5,000 added for brand-new operators


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half-up (away from zero)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round a Decimal to one decimal place, half-up."""
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# --- net_sales (SCAFFOLD §1.3 net_sales / PRD §3.8) ---
def net_sales(gross_sales_cents, discounts_cents):
    """net_sales_cents = max(0, gross - discounts); integer cents, no rounding."""
    return max(0, gross_sales_cents - discounts_cents)


# --- royalty (SCAFFOLD §1.3 royalty / PRD §3.9) ---
def royalty_cents(basis, t1_rate, t2_rate, t3_rate):
    """Marginal tiered royalty; sum the three tier contributions, then round
    half-up once on the summed total (NOT per tier)."""
    t1 = min(basis, TIER1_CEILING_CENTS)
    t2 = max(0, min(basis, TIER2_CEILING_CENTS) - TIER1_CEILING_CENTS)
    t3 = max(0, basis - TIER2_CEILING_CENTS)
    raw = (Decimal(t1) * Decimal(str(t1_rate))
           + Decimal(t2) * Decimal(str(t2_rate))
           + Decimal(t3) * Decimal(str(t3_rate)))
    return round_half_up_cents(raw)


# --- ad_fund (SCAFFOLD §1.3 ad_fund / PRD §3.9) ---
def ad_fund_cents(basis, ad_fund_rate):
    return round_half_up_cents(Decimal(basis) * Decimal(str(ad_fund_rate)))


# --- late_fee (SCAFFOLD §1.3 late_fee / PRD §3.9) ---
def late_fee_simple(principal, monthly_rate, months_late):
    """Provisional (ISSUED->OVERDUE): linear, no compounding."""
    raw = Decimal(principal) * Decimal(str(monthly_rate)) * Decimal(months_late)
    return round_half_up_cents(raw)


def late_fee_compound(principal, monthly_rate, months_late):
    """Final (OVERDUE->WRITTEN_OFF): compounded."""
    factor = (Decimal(1) + Decimal(str(monthly_rate))) ** months_late - Decimal(1)
    raw = Decimal(principal) * factor
    return round_half_up_cents(raw)


# --- audit_score (SCAFFOLD §1.3 audit_score / PRD §3.7) ---
def audit_scores(food, clean, service, brand_comp):
    """Returns (weighted_score:Decimal(1dp), overall_score:Decimal(1dp), grade:str).

    weighted_score rounded half-up to 1dp BEFORE the cap and grade banding.
    """
    weighted = (Decimal(food) * W_FOOD + Decimal(clean) * W_CLEAN
                + Decimal(service) * W_SERVICE + Decimal(brand_comp) * W_BRAND)
    weighted_score = round_half_up_1dp(weighted)

    if food < CRITICAL_FOOD_SAFETY_FLOOR:
        overall = min(weighted_score, CRITICAL_FAIL_CAP)
    else:
        overall = weighted_score

    if overall >= PASS_FLOOR:
        grade = "PASS"
    elif overall >= CONDITIONAL_FLOOR:
        grade = "CONDITIONAL"
    else:
        grade = "FAIL"
    return weighted_score, overall, grade


# --- transfer_fee (SCAFFOLD §1.3 transfer_fee / PRD §3.9) ---
def transfer_fee_cents(trailing_basis, transfer_fee_rate, buyer_is_existing_operator):
    pct = round_half_up_cents(Decimal(trailing_basis) * Decimal(str(transfer_fee_rate)))
    base_fee = max(FLAT_MIN_CENTS, pct)
    training = 0 if buyer_is_existing_operator else TRAINING_FEE_CENTS
    return base_fee + training


# --- rebate_distribution (SCAFFOLD §1.3 rebate_distribution / PRD §3.9) ---
def floor_div_cents(pool, qp, total_q):
    """floor(pool * qp / total_q) using exact integer arithmetic."""
    raw = Decimal(pool) * Decimal(qp) / Decimal(total_q)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def rebate_distribution(pool, eligible):
    """eligible: list of dicts each with 'qualifying_purchase_cents', 'created_at',
    '_seq', 'id'. Returns {id: share_cents}. Floors per-unit shares, then hands
    out the remainder one cent at a time ordered by qualifying_purchase_cents DESC,
    tie-break created_at ASC (never id)."""
    total_q = sum(a["qualifying_purchase_cents"] for a in eligible)
    shares = {a["id"]: 0 for a in eligible}
    if total_q == 0:
        return shares  # every unit gets 0, no distribution
    for a in eligible:
        shares[a["id"]] = floor_div_cents(pool, a["qualifying_purchase_cents"], total_q)
    remainder = pool - sum(shares.values())
    # order by (-qualifying_purchase_cents, created_at ASC). _seq is a stable,
    # monotonic creation order that matches created_at ASC even when created_at
    # millisecond timestamps collide.
    ordered = sorted(eligible, key=lambda a: (-a["qualifying_purchase_cents"], a["_seq"]))
    i = 0
    n = len(ordered)
    while remainder > 0 and n > 0:
        shares[ordered[i % n]["id"]] += 1
        remainder -= 1
        i += 1
    return shares
