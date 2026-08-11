"""Calculation rules per scaffold §1.3 and PRD §3.2."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# escrow_fee_schedule constants
TIER1_CAP = 50000000       # $500,000 in cents
TIER1_BPS = 30
TIER2_CAP = 200000000      # $2,000,000 in cents
TIER2_BPS = 20
TIER3_BPS = 10
MIN_FEE_CENTS = 150000     # $1,500
TRUST_SURCHARGE_CENTS = 75000  # $750
FEE_CAP_CENTS = 2500000    # $25,000

# closing_proration constants
DAYS_PER_YEAR = 365
MONTHS_PER_YEAR = 12
PARTIAL_MONTH_DAY_CUTOFF = 15


def _round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_proration(annual_fee_cents: int, method: str, expected_close_date: str) -> int:
    """closing_proration per scaffold §1.3 / PRD §3.2.1.

    DAILY: days strictly after expected_close_date through Dec 31 same year, inclusive.
    MONTHLY: full months strictly after the closing month + half-month credit if day <= 15.
    """
    year, month, day = (int(p) for p in expected_close_date.split("-"))

    if method == "DAILY":
        # days strictly after expected_close_date through Dec 31 (inclusive of Dec 31)
        dec31 = date(year, 12, 31)
        close = date(year, month, day)
        days_remaining = (dec31 - close).days  # Dec31 is included; close date excluded
        if days_remaining < 0:
            days_remaining = 0
        amount = Decimal(annual_fee_cents) * Decimal(days_remaining) / Decimal(DAYS_PER_YEAR)
        return _round_half_up_int(amount)

    # MONTHLY
    full_months = MONTHS_PER_YEAR - month  # months strictly after closing month
    per_month = _round_half_up_int(Decimal(annual_fee_cents) / Decimal(MONTHS_PER_YEAR))
    half_month = (
        _round_half_up_int(Decimal(annual_fee_cents) / Decimal(24))
        if day <= PARTIAL_MONTH_DAY_CUTOFF
        else 0
    )
    return full_months * per_month + half_month


def compute_escrow_fee(purchase_price_cents: int, proration_amount_cents: int, requires_trust: bool) -> int:
    """escrow_fee_schedule per scaffold §1.3 / PRD §3.2.2."""
    base = purchase_price_cents + proration_amount_cents

    tier1_amt = min(base, TIER1_CAP)
    tier1 = _round_half_up_int(Decimal(tier1_amt) * Decimal(TIER1_BPS) / Decimal(10000))

    tier2_amt = max(0, min(base, TIER2_CAP) - TIER1_CAP)
    tier2 = _round_half_up_int(Decimal(tier2_amt) * Decimal(TIER2_BPS) / Decimal(10000))

    tier3_amt = max(0, base - TIER2_CAP)
    tier3 = _round_half_up_int(Decimal(tier3_amt) * Decimal(TIER3_BPS) / Decimal(10000))

    tier_sum = tier1 + tier2 + tier3

    fee = max(tier_sum, MIN_FEE_CENTS)
    if requires_trust:
        fee += TRUST_SURCHARGE_CENTS
    fee = min(fee, FEE_CAP_CENTS)
    return fee


def compute_effective_payoff(release: dict, record_date: date) -> int:
    """effective_lien_payoff per scaffold §1.3 / PRD §3.4."""
    basis = release.get("payoff_basis")
    quoted = release["quoted_payoff_cents"]
    if basis == "FLAT":
        return quoted
    # PER_DIEM
    per_diem = release["per_diem_cents"]
    quote_dt = date.fromisoformat(release["quote_date"])
    gtd = date.fromisoformat(release["good_through_date"])
    elapsed = (record_date - quote_dt).days
    max_days = (gtd - quote_dt).days
    days = min(elapsed, max_days)
    if days < 0:
        days = 0
    return quoted + per_diem * days


def compute_lien_priority_ranks(liens: list) -> list:
    """lien_priority_ranking per scaffold §1.3 / PRD §3.3.1.

    Returns list of (lien_id, rank) pairs.
    """
    def sort_key(lien):
        lt = lien["lien_type"]
        if lt == "IR_INTEREST":
            cls = 1
            date_key = lien.get("ir_registered_at") or ""
        elif lt == "FAA_RECORDED":
            cls = 2
            date_key = lien["filed_at"]
        else:  # STATE or JUDGMENT
            cls = 3
            date_key = lien["filed_at"]
        return (cls, date_key, lien["created_at"])

    sorted_liens = sorted(liens, key=sort_key)
    return [(ln["id"], idx + 1) for idx, ln in enumerate(sorted_liens)]
