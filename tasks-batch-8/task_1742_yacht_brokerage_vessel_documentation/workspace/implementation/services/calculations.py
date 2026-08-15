"""Calculation rules: commission_split, sales_use_tax, proration_aggregator,
lien_payoff_waterfall, closing_total, escrow_interest_accrual,
documentation_fee, deposit_requirement. Money is integer cents; Decimal with
ROUND_HALF_UP everywhere a fractional cent can appear."""
from decimal import Decimal, ROUND_HALF_UP
from db import clock, days_in_month, parse_iso


# --- commission_split constants ---
TIER_LOW_RATE = Decimal("0.10")
TIER_MID_RATE = Decimal("0.08")
TIER_HIGH_RATE = Decimal("0.06")
CO_BROKER_SHARE = Decimal("0.50")
TIER_LOW_THRESHOLD = 500_000_000        # USD 5,000,000 in cents
TIER_HIGH_THRESHOLD = 2_000_000_000     # USD 20,000,000 in cents
PREMIER_MULTIPLIER = Decimal("1.10")
BOUTIQUE_FLAT_RATE = Decimal("0.05")

# --- sales_use_tax constants ---
STATE_RATE = {
    "FL": Decimal("0.06"), "CA": Decimal("0.0725"), "WA": Decimal("0.065"),
    "NY": Decimal("0.04"), "TX": Decimal("0.0625"), "RI": Decimal("0.07"),
    "MD": Decimal("0.06"), "NC": Decimal("0.0475"), "SC": Decimal("0.06"),
    "MA": Decimal("0.0625"), "GA": Decimal("0.04"), "NJ": Decimal("0.06625"),
}
NO_CAP = 9223372036854775807
STATE_CAP_CENTS = {
    "FL": 1_800_000, "CA": NO_CAP, "WA": NO_CAP, "NY": NO_CAP, "TX": NO_CAP,
    "RI": NO_CAP, "MD": NO_CAP, "NC": NO_CAP, "SC": 3_000_000, "MA": NO_CAP,
    "GA": NO_CAP, "NJ": NO_CAP,
}

# --- proration_aggregator constants ---
SLIP_FEE_CENTS = 450_000       # $4,500/month
FUEL_CREDIT_CENTS = 75_000     # flat credit

# --- escrow_interest_accrual constants ---
PROV_RATE = Decimal("0.0100")
FINAL_RATE = Decimal("0.0125")
PROV_DAY_BASE = 360
FINAL_DAY_BASE = 365

# --- documentation_fee constants ---
COD_FLAT_CENTS = 13_300
PER_FOOT_CENTS = 400
STATE_TITLE_RATE = Decimal("0.0015")
STATE_TITLE_CAP_CENTS = {
    "FL": 200_000, "CA": 250_000, "WA": 225_000, "NY": 200_000,
    "TX": 200_000, "RI": 200_000, "MD": 200_000, "NC": 200_000,
    "SC": 200_000, "MA": 200_000, "GA": 200_000, "NJ": 200_000,
}

MAX_DEPOSIT_MULTIPLE = 2


def round_half_up_cents(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# deposit_requirement
# ---------------------------------------------------------------------------

def required_deposit_cents(offer_price_cents: int, deposit_pct_basis: int) -> int:
    """round_half_up(offer_price_cents * deposit_pct_basis / 10000)"""
    return round_half_up_cents(
        Decimal(offer_price_cents) * Decimal(deposit_pct_basis) / Decimal(10000)
    )


# ---------------------------------------------------------------------------
# commission_split
# ---------------------------------------------------------------------------

def commission_split(gross_price_cents: int, tier_code: str, same_brokerage: bool):
    """Returns (commission_cents, listing_side_cents, selling_side_cents)."""
    if tier_code == "BOUTIQUE":
        # flat 0.05 regardless of gross tier; bypasses tier selection
        rate = BOUTIQUE_FLAT_RATE
    else:
        if gross_price_cents < TIER_LOW_THRESHOLD:
            rate = TIER_LOW_RATE
        elif gross_price_cents < TIER_HIGH_THRESHOLD:
            rate = TIER_MID_RATE
        else:
            rate = TIER_HIGH_RATE
        if tier_code == "PREMIER":
            rate = rate * PREMIER_MULTIPLIER
    # Step 2 — gross commission rounded BEFORE split
    commission_cents = round_half_up_cents(Decimal(gross_price_cents) * rate)
    # Step 3 — co-broke split
    if same_brokerage:
        listing_side_cents = commission_cents
        selling_side_cents = 0
    else:
        selling_side_cents = round_half_up_cents(Decimal(commission_cents) * CO_BROKER_SHARE)
        listing_side_cents = commission_cents - selling_side_cents  # remainder, never re-rounded
    return commission_cents, listing_side_cents, selling_side_cents


# ---------------------------------------------------------------------------
# sales_use_tax
# ---------------------------------------------------------------------------

def sales_tax_for(gross_price_cents: int, situs: str):
    """Returns (basis_cents, amount_cents) for a SALES_TAX assessment."""
    rate = STATE_RATE[situs]
    cap = STATE_CAP_CENTS[situs]
    uncapped = round_half_up_cents(Decimal(gross_price_cents) * rate)
    amount = min(uncapped, cap)
    return gross_price_cents, amount


def use_tax_credit(basis_cents: int, home_state: str, sales_tax_paid: int) -> int:
    """use_tax_due_home = max(0, home_rate*basis - sales_tax_paid)"""
    if home_state not in STATE_RATE:
        return 0
    home_uncapped = round_half_up_cents(Decimal(basis_cents) * STATE_RATE[home_state])
    return max(0, home_uncapped - sales_tax_paid)


# ---------------------------------------------------------------------------
# proration_aggregator
# ---------------------------------------------------------------------------

def prorations_cents():
    """Per-day round_half_up first, THEN multiply by remaining days; fuel credit
    added after, unrounded. Signed (credit to seller positive)."""
    now = clock.now()
    dim = days_in_month(now)
    per_day = round_half_up_cents(Decimal(SLIP_FEE_CENTS) / Decimal(dim))
    days_remaining = dim - now.day + 1  # inclusive of closing day
    return per_day * days_remaining + FUEL_CREDIT_CENTS


# ---------------------------------------------------------------------------
# escrow_interest_accrual
# ---------------------------------------------------------------------------

def interest_cents(amount_cents: int, value_date_iso: str, rate: Decimal, day_base: int) -> int:
    """round_half_up(amount * rate * days_elapsed / day_count_base), per entry."""
    value_dt = parse_iso(value_date_iso)
    now = clock.now()
    days = (now.date() - value_dt.date()).days
    if days < 0:
        days = 0
    return round_half_up_cents(
        Decimal(amount_cents) * rate * Decimal(days) / Decimal(day_base)
    )


def provisional_interest(amount_cents: int, value_date_iso: str) -> int:
    return interest_cents(amount_cents, value_date_iso, PROV_RATE, PROV_DAY_BASE)


def final_interest(amount_cents: int, value_date_iso: str) -> int:
    return interest_cents(amount_cents, value_date_iso, FINAL_RATE, FINAL_DAY_BASE)


# ---------------------------------------------------------------------------
# documentation_fee
# ---------------------------------------------------------------------------

def documentation_fee(documentation_mode: str, length_overall_ft, gross_basis_cents: int, situs: str) -> int:
    if documentation_mode == "USCG":
        whole_feet = round_half_up_cents(Decimal(str(length_overall_ft)))
        return COD_FLAT_CENTS + whole_feet * PER_FOOT_CENTS
    else:
        fee = round_half_up_cents(Decimal(gross_basis_cents) * STATE_TITLE_RATE)
        return min(fee, STATE_TITLE_CAP_CENTS[situs])
