"""Calculation rules (SCAFFOLD §1.3, PRD §3.4–§3.7).

All monetary quantities are integer cents. Only the bond penal sum and the
statutory fiduciary fee produce non-integer intermediates; both use round-half-up,
at the exact step specified.
"""

from decimal import Decimal, ROUND_HALF_UP

# ---- expenditure_routing ----
COURT_APPROVAL_THRESHOLD_CENTS = 1000000

# ---- accounting_reconciliation ----
VARIANCE_TOLERANCE_CENTS = 500

# ---- fiduciary_fee ----
TIER1_CAP_CENTS = 4999990
TIER2_CAP_CENTS = 19999990
TIER1_RATE = Decimal("0.05")
TIER2_RATE = Decimal("0.04")
TIER3_RATE = Decimal("0.03")
PUBLIC_AGENCY_FEE_CAP_CENTS = 300000

# ---- bond_amount_required ----
BOND_CORE_CAP_CENTS = 10000000
BOND_FLOOR_CENTS = 500000
PLENARY_RESERVE_CENTS = 1000000

# ---- accounting period ----
ACCOUNTING_PERIOD_DAYS = 365


def _round_half_up(value):
    """Round a Decimal to a whole integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expenditure_requires_court_approval(amount_cents, category):
    """True when amount strictly exceeds the threshold OR category is ADMIN."""
    return (amount_cents > COURT_APPROVAL_THRESHOLD_CENTS) or (category == "ADMIN")


def bond_amount_required(liquid_estate_cents, annual_income_cents, case_type):
    """Court-required penal sum in cents.

    exposure = liquid + one year income; core (first 10M) buffered 1.00x, excess
    buffered 1.10x; PLENARY adds a 1M reserve; round half up; floor 500,000.
    """
    exposure = liquid_estate_cents + annual_income_cents
    core = min(exposure, BOND_CORE_CAP_CENTS)
    excess = max(0, exposure - BOND_CORE_CAP_CENTS)
    raw = Decimal(core) * Decimal("1.00") + Decimal(excess) * Decimal("1.10")
    if case_type == "PLENARY":
        raw = raw + Decimal(PLENARY_RESERVE_CENTS)
    return max(BOND_FLOOR_CENTS, _round_half_up(raw))


def fiduciary_fee(opening_balance_cents, reported_income_cents, fiduciary_kind):
    """Statutory tiered fee with per-band round-half-up THEN sum; PUBLIC_AGENCY capped."""
    base = opening_balance_cents + reported_income_cents
    b1 = min(base, TIER1_CAP_CENTS)
    b2 = max(0, min(base, TIER2_CAP_CENTS) - TIER1_CAP_CENTS)
    b3 = max(0, base - TIER2_CAP_CENTS)
    statutory = (
        _round_half_up(Decimal(b1) * TIER1_RATE)
        + _round_half_up(Decimal(b2) * TIER2_RATE)
        + _round_half_up(Decimal(b3) * TIER3_RATE)
    )
    if fiduciary_kind == "PUBLIC_AGENCY":
        return min(statutory, PUBLIC_AGENCY_FEE_CAP_CENTS)
    return statutory
