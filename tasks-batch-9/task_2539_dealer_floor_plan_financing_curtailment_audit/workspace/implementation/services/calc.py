"""The nine calculations of PRD section 2.6 / section 3."""

from decimal import Decimal

import db
from services import spec


# --------------------------------------------------------------------------
# unit_advance_amount (3.3)
# --------------------------------------------------------------------------


def invoice_age_days(unit, as_of):
    return db.floor_days_between(as_of, db.parse_instant(unit["invoice_date"]))


def unit_advance_amount(unit, line, as_of):
    suffix = spec.CLASS_SUFFIX[unit["inventory_class"]]
    ceiling = int(line["max_unit_advance_cents_" + suffix])
    basis = min(int(unit["invoice_amount_cents"]), ceiling)
    age_days = invoice_age_days(unit, as_of)
    effective_bps = int(line["advance_rate_bps_" + suffix])
    codes = []
    if (
        unit["inventory_class"] == "DEMONSTRATOR"
        and int(unit["odometer_miles"]) > spec.DEMO_HIGH_MILEAGE_THRESHOLD
    ):
        effective_bps -= spec.DEMO_HIGH_MILEAGE_HAIRCUT_BPS
        codes.append(spec.RATE_ADJUSTMENT_HIGH_MILEAGE)
    if age_days >= spec.AGED_INVOICE_DAYS:
        effective_bps -= spec.AGED_INVOICE_HAIRCUT_BPS
        codes.append(spec.RATE_ADJUSTMENT_AGED_INVOICE)
    effective_bps = max(0, effective_bps)
    # One single rounding, after both reductions folded into the rate.
    amount = db.apply_bps(basis, effective_bps)
    return {
        "basis_cents": basis,
        "invoice_age_days": age_days,
        "effective_advance_rate_bps": effective_bps,
        "rate_adjustment_codes": codes,
        "advance_amount_cents": amount,
    }


# --------------------------------------------------------------------------
# curtailment_requirement (3.4) -- two variants
# --------------------------------------------------------------------------


def cumulative_requirement(advance_amount_cents, cumulative_paydown_bps):
    return db.apply_bps(advance_amount_cents, cumulative_paydown_bps)


def forward_projected_schedule(advance_amount_cents, tiers):
    """[(tier, projected_principal_cents)] over the rungs that create obligations."""
    schedule = []
    previous_cumulative = 0
    for tier in tiers:
        if int(tier["cumulative_paydown_bps"]) <= 0:
            continue
        cumulative = cumulative_requirement(
            advance_amount_cents, int(tier["cumulative_paydown_bps"])
        )
        schedule.append((tier, cumulative - previous_cumulative))
        previous_cumulative = cumulative
    return schedule


def assessed_requirement(unit, cumulative_paydown_bps):
    cumulative = cumulative_requirement(
        int(unit["advance_amount_cents"]), int(cumulative_paydown_bps)
    )
    difference = cumulative - int(unit["principal_paid_cents"])
    return max(0, min(difference, int(unit["outstanding_principal_cents"])))


# --------------------------------------------------------------------------
# delinquency_assessment (3.4) -- round before the ceiling
# --------------------------------------------------------------------------


def late_fee_cents(required_principal_cents):
    raw = db.apply_bps(required_principal_cents, spec.LATE_FEE_BPS)
    return min(spec.LATE_FEE_CAP_CENTS, raw)


# --------------------------------------------------------------------------
# observation_classification (3.6)
# --------------------------------------------------------------------------


def classify_observation(observed_condition, title_verified, snapshot_cents):
    if observed_condition == "PRESENT":
        if title_verified:
            return "VERIFIED", False
        return "TITLE_EXCEPTION", False
    if observed_condition == "PRESENT_DAMAGED":
        return "DAMAGE_EXCEPTION", False
    if observed_condition == "WHOLESALED":
        return "WHOLESALE_EXCEPTION", int(snapshot_cents) > 0
    # SOLD_NO_PAYOFF and MISSING
    return "SOLD_OUT_OF_TRUST", True


SOT_ELIGIBILITY_BY_CLASSIFICATION = {
    "SOLD_OUT_OF_TRUST": ("INELIGIBLE_SOLD_OUT_OF_TRUST", "SOLD_OUT_OF_TRUST"),
    "WHOLESALE_EXCEPTION": ("INELIGIBLE_WHOLESALE", "WHOLESALE"),
    "TITLE_EXCEPTION": ("INELIGIBLE_TITLE_DEFECT", "TITLE_DEFECT"),
    "DAMAGE_EXCEPTION": ("INELIGIBLE_DAMAGE", "DAMAGE"),
}


# --------------------------------------------------------------------------
# covenant_dscr (3.8) -- dual variant, four decimal places
# --------------------------------------------------------------------------


def covenant_ratios(ebitda_cents, interest_cents, curtailment_paid_cents):
    denominator = int(interest_cents) + int(curtailment_paid_cents)
    if denominator == 0:
        undefined = Decimal(spec.DSCR_UNDEFINED)
        return undefined, undefined
    lender_standard = db.ratio_4dp(int(ebitda_cents), denominator)
    dealer_adjusted = db.ratio_4dp(int(ebitda_cents) + int(interest_cents), denominator)
    return lender_standard, dealer_adjusted


def required_tangible_net_worth(credit_limit_cents):
    return db.apply_bps(credit_limit_cents, spec.TNW_REQUIREMENT_BPS)


def trailing_sot_incident_count(dealer_id, period_end):
    """Incidents created within the 365-day window ending on the period close."""
    window_end_exclusive = db.add_days(db.midnight(period_end), 1)
    window_start = db.add_days(db.midnight(period_end), -364)
    count = 0
    for incident in db.rows("incidents"):
        if incident["dealer_id"] != dealer_id:
            continue
        if incident["status"] not in spec.INCIDENT_STATUSES:
            continue
        created = db.parse_instant(incident["created_at"])
        if window_start <= created < window_end_exclusive:
            count += 1
    return count
