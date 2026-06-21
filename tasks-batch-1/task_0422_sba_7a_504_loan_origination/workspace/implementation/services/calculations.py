"""Calculation rules — SCAFFOLD §1.3 / PRD §3.

All money is integer cents. Each calculation pins its own rounding discipline
(round_half_up vs floor) and, where a sum of components is involved, the order
(floor-per-component-then-sum). We use Decimal with explicit ROUND_HALF_UP /
ROUND_FLOOR to avoid IEEE-754 drift.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def round_half_up(value):
    """round_half_up to whole cents. `value` may be Decimal/int/float."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(value):
    """floor (truncation toward zero for non-negative money) to whole cents."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# --- size_standard (Application submit) --------------------------------------
TNW_CAP = 2000000000        # $20,000,000
NET_INCOME_CAP = 650000000  # $6,500,000
EMPLOYEE_CAP = 500


def size_standard(borrower):
    """Alternative size standard: PASS if EITHER prong holds. Caps INCLUSIVE."""
    financial_ok = (
        borrower["tangible_net_worth_cents"] <= TNW_CAP
        and borrower["avg_net_income_cents"] <= NET_INCOME_CAP
    )
    headcount_ok = borrower["affiliate_employee_count"] <= EMPLOYEE_CAP
    return financial_ok or headcount_ok


# --- collateral_coverage -----------------------------------------------------
ASSET_DISCOUNT = {
    "REAL_ESTATE": Decimal("0.80"),
    "EQUIPMENT": Decimal("0.50"),
    "INVENTORY": Decimal("0.30"),
    "RECEIVABLES": Decimal("0.50"),
}
SHORT_TERM_COVERAGE = Decimal("0.50")


def collateral_item_discounted_value(asset_type, appraised_value_cents, prior_lien_cents):
    """Per-item net liquidation value: floor(appraised * discount) - prior_lien,
    floored at 0 (round-per-item)."""
    discount = ASSET_DISCOUNT[asset_type]
    discounted = floor_int(Decimal(appraised_value_cents) * discount)
    return max(0, discounted - prior_lien_cents)


def collateral_coverage_ok(collateral_items, maturity_months, requested_amount_cents):
    """Sum per-item discounted values (already floored at create), compare to the
    maturity-dependent requirement. Boundary INCLUSIVE (>=)."""
    total_discounted = sum(ci["discounted_value_cents"] for ci in collateral_items)
    if maturity_months > 120:
        required = requested_amount_cents
    else:
        required = floor_int(Decimal(requested_amount_cents) * SHORT_TERM_COVERAGE)
    return total_discounted >= required


# --- guaranty_amount (authorize) ---------------------------------------------
def guaranty_amount(requested_amount_cents, guaranty_pct):
    return round_half_up(Decimal(requested_amount_cents) * Decimal(str(guaranty_pct)))


# --- guaranty_fee (authorize) ------------------------------------------------
TIER1_CENTS = 15000000   # $150,000
TIER2_CENTS = 70000000   # $700,000
RATE1 = Decimal("0.02")
RATE2 = Decimal("0.03")
RATE3 = Decimal("0.035")


def guaranty_fee(requested_amount_cents, guaranty_pct):
    """Marginal tiered upfront fee. FLOOR per band, THEN sum (pinned order)."""
    g = requested_amount_cents
    gp = Decimal(str(guaranty_pct))
    band1 = min(g, TIER1_CENTS)
    band2 = min(max(g - TIER1_CENTS, 0), TIER2_CENTS - TIER1_CENTS)
    band3 = max(g - TIER2_CENTS, 0)
    fee = (
        floor_int(Decimal(band1) * gp * RATE1)
        + floor_int(Decimal(band2) * gp * RATE2)
        + floor_int(Decimal(band3) * gp * RATE3)
    )
    return fee


# --- secondary_market_premium (guaranty-sale settle) -------------------------
LENDER_RETAINED_BPS = 100
SBA_SPLIT = Decimal("0.50")


def secondary_market_premium(sold_principal_cents, premium_bps):
    gross_premium = floor_int(Decimal(sold_principal_cents) * Decimal(premium_bps) / Decimal(10000))
    lender_retained = floor_int(Decimal(sold_principal_cents) * Decimal(LENDER_RETAINED_BPS) / Decimal(10000))
    if gross_premium <= lender_retained:
        sba_cut = 0
    else:
        sba_cut = floor_int(Decimal(gross_premium - lender_retained) * SBA_SPLIT)
    return gross_premium - sba_cut


# --- liquidation_split (liquidation settle) ----------------------------------
def liquidation_split(recovery_cents, expense_cents, guaranty_pct):
    """Returns (net_recovery, sba_share, lender_share). Conserves net_recovery."""
    net_recovery = max(0, recovery_cents - expense_cents)
    sba_share = round_half_up(Decimal(net_recovery) * Decimal(str(guaranty_pct)))
    lender_share = net_recovery - sba_share
    return net_recovery, sba_share, lender_share


# --- guaranty_purchase_payout (guaranty-purchase pay) ------------------------
def guaranty_purchase_payout(outstanding_principal_cents, guaranty_pct,
                             claimed_principal_cents, repair_pct,
                             sba_recovery_credit):
    cap = round_half_up(Decimal(outstanding_principal_cents) * Decimal(str(guaranty_pct)))
    base = min(claimed_principal_cents, cap)
    after_recovery = max(0, base - sba_recovery_credit)
    approved = floor_int(Decimal(after_recovery) * (Decimal(1) - Decimal(str(repair_pct))))
    return approved


# --- ongoing_fee (servicing-report accept) -----------------------------------
ANNUAL_ONGOING_RATE = Decimal("0.0055")


def ongoing_fee(outstanding_principal_cents, guaranty_pct):
    guaranteed_outstanding = round_half_up(
        Decimal(outstanding_principal_cents) * Decimal(str(guaranty_pct))
    )
    return floor_int(Decimal(guaranteed_outstanding) * ANNUAL_ONGOING_RATE / Decimal(12))
