"""The eight pinned calculations (PRD 2.6, 3.2, 3.5, 3.6, 3.7).

All money is integer cents; every division is carried at exact rational
precision (fractions.Fraction) and rounded half up exactly where the spec says.
"""
import math
from fractions import Fraction

from db import db, sort_key
from util import round_half_up

# ---- ce_compliance_evaluation -------------------------------------------------
REQUIRED_FEDERAL_LAW_HOURS = 3
REQUIRED_ETHICS_HOURS = 2
REQUIRED_NONTRADITIONAL_HOURS = 2
DEFAULT_REQUIRED_CE_HOURS = 8
MAKEUP_ATTRIBUTION = "MAKEUP_ATTRIBUTION"
CALENDAR_YEAR_ATTRIBUTION = "CALENDAR_YEAR_ATTRIBUTION"
ATTRIBUTION_VARIANTS = (MAKEUP_ATTRIBUTION, CALENDAR_YEAR_ATTRIBUTION)

# ---- volume_tier_bps_selection ----------------------------------------------
TIER1_MAX_UNITS = 4
TIER2_MAX_UNITS = 9
TIER1_BPS = 0
TIER2_BPS = 15
TIER3_BPS = 30
QUALITY_FULL_MIN = 90
QUALITY_PARTIAL_MIN = 70
QUALITY_PARTIAL_PENALTY_BPS = 10
QUALITY_FAIL_PENALTY_BPS = 25
HOURS_MIN_PCT = 50
HOURS_CAP_BPS = 15

# ---- originator_compensation_accrual ---------------------------------------
BPS_DENOMINATOR = 10000

# ---- pricing_exception_net_impact ------------------------------------------
CONCESSION_BRACKET_CENTS = 300000
ABSORB_HIGH_PCT = 50
ABSORB_LOW_PCT = 25
CONCESSION_CAP_PCT = 2

# ---- early_payoff_clawback -------------------------------------------------
EARLY_PAYOFF_INNER_DAYS = 90
EARLY_PAYOFF_OUTER_DAYS = 180
INNER_RECAPTURE_PCT = 100
OUTER_RECAPTURE_PCT = 50

# ---- dual_comp_steering_exposure_score -------------------------------------
DUAL_WEIGHT = Fraction(35, 100)
SPREAD_WEIGHT = Fraction(25, 100)
EXCEPTION_WEIGHT = Fraction(15, 100)
CLAWBACK_WEIGHT = Fraction(25, 100)
SPREAD_CAP_BPS = 100
ELEVATED_THRESHOLD = 60

CLOSED_STATUSES = ("CLOSED", "PAID_OFF")


# =============================================================================
# Continuing education
# =============================================================================
def ce_aggregate(originator_id, target_year, variant):
    """Total / federal-law / ethics / non-traditional hours over the counted set.
    Only APPLIED credits are ever counted."""
    total = federal = ethics = nontraditional = 0
    for credit in db.ce_credits.values():
        if credit["originator_id"] != originator_id:
            continue
        if credit["credit_status"] != "APPLIED":
            continue
        if variant == CALENDAR_YEAR_ATTRIBUTION:
            if credit["completion_date"].year != target_year:
                continue
        else:
            if credit["attributed_year"] != target_year:
                continue
        hours = credit["credit_hours"]
        total += hours
        if credit["category"] == "FEDERAL_LAW":
            federal += hours
        elif credit["category"] == "ETHICS":
            ethics += hours
        elif credit["category"] == "NONTRADITIONAL":
            nontraditional += hours
    return total, federal, ethics, nontraditional


def ce_satisfied(total, federal, ethics, nontraditional, required_hours):
    """All four minimums are inclusive."""
    return (total >= required_hours
            and federal >= REQUIRED_FEDERAL_LAW_HOURS
            and ethics >= REQUIRED_ETHICS_HOURS
            and nontraditional >= REQUIRED_NONTRADITIONAL_HOURS)


# =============================================================================
# Volume tier adder
# =============================================================================
def volume_tier_bps(plan, loan, units):
    if not plan.get("volume_tier_enabled"):
        return 0
    if units <= TIER1_MAX_UNITS:
        tier_bps = TIER1_BPS
    elif units <= TIER2_MAX_UNITS:
        tier_bps = TIER2_BPS
    else:
        tier_bps = TIER3_BPS
    quality = loan.get("file_quality_score") or 0
    if quality >= QUALITY_FULL_MIN:
        penalty = 0
    elif quality >= QUALITY_PARTIAL_MIN:
        penalty = QUALITY_PARTIAL_PENALTY_BPS
    else:
        penalty = QUALITY_FAIL_PENALTY_BPS
    # The clamp order is pinned: subtract, then min against TIER3_BPS, then max 0.
    adder = max(0, min(TIER3_BPS, tier_bps - penalty))
    if (loan.get("hours_worked_pct") or 0) < HOURS_MIN_PCT:
        adder = min(adder, HOURS_CAP_BPS)
    return adder


# =============================================================================
# Per-line commission
# =============================================================================
def approved_exception_for(loan_id):
    rows = [e for e in db.pricing_exceptions.values()
            if e["loan_application_id"] == loan_id and e["status"] == "APPROVED"]
    if not rows:
        return None
    rows.sort(key=sort_key)
    return rows[0]


def clamp_fee(plan, cents):
    return min(plan["max_fee_cents"], max(plan["min_fee_cents"], cents))


def accrual_line(plan, loan, amount_cents, units):
    """Returns (tier_bps_adder, base_comp_cents, comp_impact_cents, accrued_cents)."""
    tier = volume_tier_bps(plan, loan, units)
    effective_bps = plan["base_basis_points"] + tier
    raw = Fraction(int(amount_cents or 0) * effective_bps, BPS_DENOMINATOR)
    base_comp = round_half_up(raw)
    base_comp = clamp_fee(plan, base_comp)
    comp_impact = 0
    if plan.get("concession_absorption_enabled"):
        exception = approved_exception_for(loan["id"])
        if exception is not None:
            comp_impact = exception["comp_impact_cents"] or 0
    return tier, base_comp, comp_impact, base_comp - comp_impact


def provisional_inputs(loan):
    """PROVISIONAL: the locked amount and the closed-unit count strictly before
    this loan."""
    units = (loan.get("closed_unit_index") or 0) - 1
    if units < 0:
        units = 0
    return loan.get("locked_amount_cents") or 0, units


def final_units(originator_id):
    """FINAL: forward-looking count of the originator's CLOSED/PAID_OFF loans at
    the instant the reconciliation run executes."""
    return len([l for l in db.loan_applications.values()
                if l["originator_id"] == originator_id
                and l["status"] in CLOSED_STATUSES])


# =============================================================================
# Pricing exception concession absorption
# =============================================================================
def concession_cap_cents(locked_amount_cents):
    return int(math.floor(Fraction(int(locked_amount_cents or 0) * CONCESSION_CAP_PCT, 100)))


def pricing_exception_impact(plan, loan, exception):
    """Returns (comp_impact_cents, net_comp_cents). Rounding happens exactly
    twice: step 1 and step 4."""
    raw = Fraction(int(loan.get("locked_amount_cents") or 0) * plan["base_basis_points"],
                   BPS_DENOMINATOR)
    base_comp = clamp_fee(plan, round_half_up(raw))
    if not plan.get("concession_absorption_enabled"):
        return 0, base_comp
    absorb_pct = ABSORB_HIGH_PCT if base_comp >= CONCESSION_BRACKET_CENTS else ABSORB_LOW_PCT
    comp_impact = round_half_up(Fraction(exception["concession_cents"] * absorb_pct, 100))
    return comp_impact, base_comp - comp_impact


# =============================================================================
# Early payoff clawback
# =============================================================================
def days_held_between(funded_at, payoff_date):
    """Elapsed seconds divided by 86400, floored to whole days. timedelta is
    normalised so that .days is exactly that floor (89d23h -> 89)."""
    return (payoff_date - funded_at).days


def recapture_pct_for(days_held):
    if days_held <= EARLY_PAYOFF_INNER_DAYS:
        return INNER_RECAPTURE_PCT
    if days_held <= EARLY_PAYOFF_OUTER_DAYS:
        return OUTER_RECAPTURE_PCT
    return 0


def clawback_cents_for(paid_cents, recapture_pct):
    return round_half_up(Fraction(int(paid_cents or 0) * recapture_pct, 100))


# =============================================================================
# Ledger conserved quantities
# =============================================================================
def records_of(originator_id):
    return [r for r in db.compensation_records.values()
            if r["originator_id"] == originator_id]


def lifetime_accrued_cents(originator_id):
    return sum((r["accrued_cents"] or 0) for r in records_of(originator_id))


def lifetime_clawed_back_cents(originator_id):
    return sum((r["clawback_cents"] or 0) for r in records_of(originator_id))


def net_compensation_cents(originator_id):
    return lifetime_accrued_cents(originator_id) - lifetime_clawed_back_cents(originator_id)


def open_investigation_count(originator_id):
    return len([i for i in db.investigations.values()
                if i["originator_id"] == originator_id
                and i["status"] in ("OPEN", "SUBSTANTIATED")])


# =============================================================================
# Steering / dual-compensation exposure score
# =============================================================================
def recompute_exposure(originator):
    """Recompute exposure_score and monitoring_status in place. Returns True
    when monitoring_status actually changed."""
    before = originator["monitoring_status"]
    closed = [l for l in db.loan_applications.values()
              if l["originator_id"] == originator["id"]
              and l["status"] in CLOSED_STATUSES]
    n = len(closed)
    if n == 0:
        originator["exposure_score"] = 0
        originator["monitoring_status"] = "STANDARD"
        return before != originator["monitoring_status"]

    dual_count = len([l for l in closed
                      if (l["lender_paid_comp_cents"] or 0) > 0
                      and (l["borrower_paid_comp_cents"] or 0) > 0])
    dual_ratio_pct = Fraction(100 * dual_count, n)

    spread_total = 0
    for loan in closed:
        note = loan.get("note_rate_bps") or 0
        par = loan.get("par_rate_bps") or 0
        spread_total += max(0, note - par)
    avg_spread_bps = Fraction(spread_total, n)
    capped_spread = min(Fraction(SPREAD_CAP_BPS), avg_spread_bps)

    exception_count = 0
    for loan in closed:
        if any(e["loan_application_id"] == loan["id"] and e["status"] == "APPROVED"
               for e in db.pricing_exceptions.values()):
            exception_count += 1
    exception_rate_pct = Fraction(100 * exception_count, n)

    accrued = lifetime_accrued_cents(originator["id"])
    clawed = lifetime_clawed_back_cents(originator["id"])
    if accrued == 0:
        clawback_ratio_pct = Fraction(0)
    else:
        clawback_ratio_pct = Fraction(100 * clawed, accrued)
    capped_clawback = min(Fraction(100), clawback_ratio_pct)

    raw = (DUAL_WEIGHT * dual_ratio_pct
           + SPREAD_WEIGHT * capped_spread
           + EXCEPTION_WEIGHT * exception_rate_pct
           + CLAWBACK_WEIGHT * capped_clawback)
    score = min(100, max(0, round_half_up(raw)))
    originator["exposure_score"] = score
    originator["monitoring_status"] = (
        "ELEVATED" if score >= ELEVATED_THRESHOLD else "STANDARD")
    return before != originator["monitoring_status"]
