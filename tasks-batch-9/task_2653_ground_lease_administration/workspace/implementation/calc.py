"""Every algorithmic rule in the specification, with its constants pinned."""

import store
from validate import rhu

# --- revaluation ------------------------------------------------------------
ARBITRATION_DIVERGENCE_THRESHOLD_BPS = 1000
MAX_NEGOTIATION_ROUNDS = 2
REVALUATION_ADVANCE_NOTICE_DAYS = 180

# --- percentage rent --------------------------------------------------------
SUBLEASE_INCLUSION_RATE_BPS = 5000
BASE_RENT_OFFSET_SHARE_BPS = 2500
UNDERREPORT_TOLERANCE_BPS = 500

# --- transfer fee -----------------------------------------------------------
ASSIGNMENT_TIER_1_CEILING_CENTS = 50000000
ASSIGNMENT_TIER_2_CEILING_CENTS = 200000000
ASSIGNMENT_TIER_1_RATE_BPS = 300
ASSIGNMENT_TIER_2_RATE_BPS = 500
ASSIGNMENT_TIER_3_RATE_BPS = 700
ASSIGNMENT_MINIMUM_FEE_CENTS = 500000
SUBLEASE_PROFIT_SHARE_BPS = 5000
ADMIN_CHARGE_RATE_BPS = 250
ADMIN_CHARGE_CAP_CENTS = 250000
LATE_SURCHARGE_TIER_CEILING_CENTS = 1000000
LATE_SURCHARGE_LOW_RATE_BPS = 250
LATE_SURCHARGE_HIGH_RATE_BPS = 500
MAX_SUBLEASE_TIER_DEPTH = 2
SUBLEASE_TURNOVER_BUFFER_DAYS = 0

# --- default and cure -------------------------------------------------------
MONETARY_CURE_DAYS = 10
INSURANCE_CURE_DAYS = 15
NON_MONETARY_CURE_DAYS = 30
NEW_LEASE_ELECTION_DAYS = 30

# --- casualty ---------------------------------------------------------------
CASUALTY_TERMINATION_THRESHOLD_BPS = 5000
DAYS_IN_YEAR_BASIS = 365

# --- reversion --------------------------------------------------------------
REVERSION_WEIGHTS = {
    "SHELL_CONDITION": {
        "structural": 6000, "envelope": 3000, "systems": 1000, "pass": 7000,
    },
    "FULLY_FITTED": {
        "structural": 4000, "envelope": 3000, "systems": 3000, "pass": 8500,
    },
    "BROOM_CLEAN": {
        "structural": 7000, "envelope": 2000, "systems": 1000, "pass": 6000,
    },
}


# ===========================================================================
# Revaluation
# ===========================================================================
def divergence_bps(lessor_rent, lessee_rent):
    """(larger - smaller) * 10000 / smaller, rounded half up."""
    larger = max(lessor_rent, lessee_rent)
    smaller = min(lessor_rent, lessee_rent)
    return rhu((larger - smaller) * 10000, smaller)


def midpoint_indicated(lessor_rent, lessee_rent):
    return rhu(lessor_rent + lessee_rent, 2)


def baseball_selection(lessor_rent, lessee_rent, independent_rent):
    """Return (indicated_rent, award_basis); an exact tie goes to the tenant."""
    gap_lessor = abs(lessor_rent - independent_rent)
    gap_lessee = abs(lessee_rent - independent_rent)
    if gap_lessor < gap_lessee:
        return lessor_rent, "CLOSEST_LESSOR"
    if gap_lessee < gap_lessor:
        return lessee_rent, "CLOSEST_LESSEE"
    return lessee_rent, "TIE_TO_LESSEE"


def collar_bounds(prior_rent, min_bps, max_bps):
    floor = prior_rent + rhu(prior_rent * min_bps, 10000)
    ceiling = prior_rent + rhu(prior_rent * max_bps, 10000)
    return floor, ceiling


def clamp_to_collar(indicated, prior_rent, min_bps, max_bps):
    """Applied last, to the already rounded indicated rent."""
    floor, ceiling = collar_bounds(prior_rent, min_bps, max_bps)
    resolved = indicated
    if resolved < floor:
        resolved = floor
    if resolved > ceiling:
        resolved = ceiling
    return resolved


# ===========================================================================
# Percentage rent
# ===========================================================================
def sublease_inclusion_base(rows):
    """Half of each row's annual rent, rounded per row, then summed."""
    total = 0
    for row in rows:
        rent = row.get("annual_sublease_rent_cents") or 0
        total += rhu(rent * SUBLEASE_INCLUSION_RATE_BPS, 10000)
    return total


def base_rent_offset_credit(current_base_rent_cents):
    return rhu(current_base_rent_cents * BASE_RENT_OFFSET_SHARE_BPS, 10000)


def percentage_rent_due(gross_sales_cents, included_sublease_rent_cents,
                        breakpoint_cents, rate_bps, current_base_rent_cents):
    """Steps two through six of the assessment computation."""
    adjusted = gross_sales_cents + included_sublease_rent_cents
    excess = adjusted - breakpoint_cents
    if excess < 0:
        excess = 0
    gross = rhu(excess * rate_bps, 10000)
    credit = base_rent_offset_credit(current_base_rent_cents)
    amount_due = gross - credit
    if amount_due < 0:
        amount_due = 0
    return gross, credit, amount_due


def underreport_penalty(reported_cents, audited_cents, rate_bps):
    """Step seven: material underreporting beyond a five per cent tolerance."""
    if audited_cents * 10000 > reported_cents * (10000 + UNDERREPORT_TOLERANCE_BPS):
        return rhu((audited_cents - reported_cents) * rate_bps, 10000)
    return 0


# ===========================================================================
# Transfer fee
# ===========================================================================
def assignment_rate_bps(net_consideration_cents):
    """Flat-by-tier: the selected rate applies to the whole consideration."""
    if net_consideration_cents <= ASSIGNMENT_TIER_1_CEILING_CENTS:
        return ASSIGNMENT_TIER_1_RATE_BPS
    if net_consideration_cents <= ASSIGNMENT_TIER_2_CEILING_CENTS:
        return ASSIGNMENT_TIER_2_RATE_BPS
    return ASSIGNMENT_TIER_3_RATE_BPS


def allocable_base_rent(current_base_rent_cents, sublet_area_sqft,
                        total_permitted_gfa_sqft):
    return rhu(current_base_rent_cents * sublet_area_sqft,
               total_permitted_gfa_sqft)


def late_surcharge(base_total_cents):
    """Rate tier selected on the base total, which excludes the surcharge."""
    if base_total_cents <= LATE_SURCHARGE_TIER_CEILING_CENTS:
        rate = LATE_SURCHARGE_LOW_RATE_BPS
    else:
        rate = LATE_SURCHARGE_HIGH_RATE_BPS
    return rhu(base_total_cents * rate, 10000)


def price_transfer(transfer, lease):
    """Return the five priced figures for a consented transfer."""
    allocable = None
    if transfer["transfer_type"] == "ASSIGNMENT":
        consideration = transfer.get("net_consideration_cents") or 0
        rate = assignment_rate_bps(consideration)
        gross = rhu(consideration * rate, 10000)
        if gross < ASSIGNMENT_MINIMUM_FEE_CENTS:
            gross = ASSIGNMENT_MINIMUM_FEE_CENTS
    else:
        allocable = allocable_base_rent(
            lease["current_annual_base_rent_cents"],
            transfer.get("sublet_area_sqft") or 0,
            lease["total_permitted_gfa_sqft"],
        )
        profit = (transfer.get("annual_sublease_rent_cents") or 0) - allocable
        if profit < 0:
            profit = 0
        gross = rhu(profit * SUBLEASE_PROFIT_SHARE_BPS, 10000)

    admin = rhu(gross * ADMIN_CHARGE_RATE_BPS, 10000)
    if admin > ADMIN_CHARGE_CAP_CENTS:
        admin = ADMIN_CHARGE_CAP_CENTS

    base_total = gross + admin
    late = late_surcharge(base_total) if transfer.get("submitted_late") else 0
    total = base_total + late
    return allocable, gross, admin, late, total


# ===========================================================================
# Cure windows
# ===========================================================================
def lessee_cure_days(default_type):
    if default_type in ("MONETARY_RENT_ARREARS", "PERCENTAGE_RENT_UNDERPAYMENT"):
        return MONETARY_CURE_DAYS
    if default_type == "INSURANCE_LAPSE":
        return INSURANCE_CURE_DAYS
    return NON_MONETARY_CURE_DAYS


def noticed_mortgages(mortgage_rows):
    """Mortgages still in RECORDED that carry a non-empty notice address."""
    return [
        m for m in mortgage_rows
        if m.get("status") == "RECORDED"
        and (m.get("notice_email") or "").strip()
    ]


def cure_deadlines(served_at, default_type, mortgage_rows):
    lessee_deadline = store.add_days(served_at, lessee_cure_days(default_type))
    noticed = noticed_mortgages(mortgage_rows)
    if not noticed:
        return lessee_deadline, None
    widest = max(m.get("cure_extension_days") or 0 for m in noticed)
    return lessee_deadline, store.add_days(lessee_deadline, widest)


# ===========================================================================
# Loss proceeds
# ===========================================================================
def bonus_value_share_bps(improvements_value_cents, reversion_land_value_cents):
    denominator = improvements_value_cents + reversion_land_value_cents
    if denominator <= 0:
        return 0
    return rhu(improvements_value_cents * 10000, denominator)


def pro_rata_share_bps(commencement_date, expiration_date, current_instant):
    total_days = store.whole_days_between(commencement_date, expiration_date)
    remaining_days = store.whole_days_between(current_instant, expiration_date)
    if total_days <= 0:
        return 0
    if remaining_days < 0:
        remaining_days = 0
    return rhu(remaining_days * 10000, total_days)


def lessee_share_bps(loss_event, lease):
    if loss_event.get("allocation_method") == "BONUS_VALUE":
        return bonus_value_share_bps(
            lease["improvements_value_cents"],
            lease["reversion_land_value_cents"],
        )
    return pro_rata_share_bps(
        lease["commencement_date"], lease["expiration_date"], store.now()
    )


def rent_abatement_bps(damaged_area_sqft, total_permitted_gfa_sqft):
    return rhu(damaged_area_sqft * 10000, total_permitted_gfa_sqft)


def casualty_termination_available(damage_estimate_cents,
                                  improvements_value_cents):
    return (damage_estimate_cents * 10000
            >= improvements_value_cents * CASUALTY_TERMINATION_THRESHOLD_BPS)


# ===========================================================================
# Reversion condition scoring
# ===========================================================================
def weighted_condition_score_bps(standard_code, structural, envelope, systems):
    weights = REVERSION_WEIGHTS[standard_code]
    total = rhu(structural * weights["structural"], 100)
    total += rhu(envelope * weights["envelope"], 100)
    total += rhu(systems * weights["systems"], 100)
    return total


def passing_score_bps(standard_code):
    return REVERSION_WEIGHTS[standard_code]["pass"]


def holdback_cents(deposit_held_cents, improvements_value_cents, deficiency):
    indicated = rhu(improvements_value_cents * deficiency, 10000)
    return min(deposit_held_cents, indicated)
