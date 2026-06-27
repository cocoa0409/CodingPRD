"""The four scaffold calculation rules, implemented exactly per PRD §3.

All amounts are integer cents; percentage steps round half up; rounding order
is pinned per the PRD where it matters."""
from helpers import pct, round_half_up
from decimal import Decimal


# --- fee_assessment (PRD §3.2) -------------------------------------------------
def fee_quoted(license_class):
    """Initial application fee: base + (rounded) zoning surcharge + (rounded)
    manufacturer surcharge. Round each surcharge BEFORE summing."""
    base = license_class["base_fee_cents"]
    zoning_surcharge = pct(base, 0.10) if license_class["requires_zoning"] else 0
    manufacturer_surcharge = (
        pct(base, 0.25) if license_class["premise_type"] == "MANUFACTURER" else 0
    )
    return base + zoning_surcharge + manufacturer_surcharge


def renewal_fee(license_class, grace_lapsed):
    """Renewal fee: base only (NO surcharges) plus a 5%-of-base late fee when the
    grace has lapsed (clock.now >= term_end_at at the moment of renewal)."""
    base = license_class["base_fee_cents"]
    fee = base
    if grace_lapsed:
        fee += pct(base, 0.05)
    return fee


# --- fine_assessment (PRD §3.9) ------------------------------------------------
_SEV_BASE = {"MINOR": 25000, "SERIOUS": 75000, "EGREGIOUS": 200000}
_DEMERIT_FOR = {"MINOR": 2, "SERIOUS": 4, "EGREGIOUS": 6}
FINE_CAP_CENTS = 500000


def fine_cents(severity, prior_demerit_points, action_type):
    """Disciplinary fine. Recidivism multiplier from the prior demerit snapshot
    (BEFORE this violation's points are added). Cap applied AFTER rounding."""
    sev_base = _SEV_BASE[severity]
    if prior_demerit_points > 8:
        recidivism = Decimal("2.0")
    elif prior_demerit_points >= 4:
        recidivism = Decimal("1.5")
    else:
        recidivism = Decimal("1.0")
    raw = Decimal(sev_base) * recidivism
    if action_type == "REVOCATION":
        fine = 0
    elif action_type == "SUSPENSION":
        fine = round_half_up(raw * Decimal("0.5"))
    else:  # FINE
        fine = round_half_up(raw)
    return min(fine, FINE_CAP_CENTS)


def demerit_for(severity):
    return _DEMERIT_FOR[severity]


# --- excise_assessment (PRD §3.11) --------------------------------------------
_TIER_MULT = {"SUPPLIER": Decimal("2.0"), "WHOLESALER": Decimal("1.0"), "RETAILER": Decimal("0.0")}


def excise_due(gross_sales_cents, tier):
    """Tiered excise with a tier-keyed compliance rebate, pinned evaluation order:
    STEP 1 marginal excise (per-band rounding); STEP 2 rebate tier from excise;
    STEP 3 apply rebate scaled by tier multiplier; final = excise - rebate >= 0."""
    g = gross_sales_cents
    t1 = min(g, 1_000_000)
    t2 = min(max(g - 1_000_000, 0), 4_000_000)
    t3 = max(g - 5_000_000, 0)
    excise = pct(t1, 0.02) + pct(t2, 0.04) + pct(t3, 0.06)

    # rebate base keyed on the EXCISE total
    if excise > 200_000:
        rebate_base = pct(excise, 0.10)
    elif excise > 50_000:
        rebate_base = pct(excise, 0.05)
    else:
        rebate_base = 0
    rebate = round_half_up(Decimal(rebate_base) * _TIER_MULT[tier])
    return max(excise - rebate, 0)
