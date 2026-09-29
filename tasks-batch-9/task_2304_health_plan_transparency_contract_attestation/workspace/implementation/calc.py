"""Every calculation in the domain, with the pinned order of operations.

All money is integer cents.  All rounding is ROUND_HALF_UP (a tie rounds away
from zero).  Exact rational arithmetic (fractions.Fraction) is used throughout so
that no binary floating point artefact can move a rounded result.
"""

from fractions import Fraction

import clock

# --- penalty pricing constants (PRD 3.9) -----------------------------------
DAILY_RATE_CENTS = {
    "MRF_REFRESH": 10000,
    "TOOL_SLA": 5000,
    "RXDC_LATE": 20000,
    "GAG_CLAUSE": 15000,
    "ATTESTATION_LATE": 12000,
}
PENALTY_CAP_CENTS = 100000000

# --- compensation reasonableness constants (PRD 3.7) ----------------------
W_PRICE = 40
W_SCOPE = 25
W_DISCLOSURE = 35
RATIO_CAP = Fraction(3, 1)
UNREASONABLE_THRESHOLD = Fraction(55)

# --- posture constants (PRD 2.8) -----------------------------------------
POINTS_MISSED_REFRESH_CYCLE = 3
POINTS_LATE_CERTIFIED_CYCLE = 2
POINTS_NON_COMPLIANT_CONTRACT = 6
POINTS_TOOL_SLA_BREACH = 2
POINTS_RXDC_LATE = 5
POINTS_ATTESTATION_LATE = 5
POINTS_UNREASONABLE_DISCLOSURE = 3
DEFICIENT_POINT_THRESHOLD = 6
FROZEN_POINT_THRESHOLD = 12

# --- misc thresholds -----------------------------------------------------
GRACE_DAYS = 5
MINUTES_PER_DAY = 1440
REQUIRED_COVERED_ITEMS = 500
MAX_NEGOTIATION_ROUNDS = 3
MAX_REMEDIATION_ROUNDS = 2
ABATEMENT_PCT = Fraction(1, 2)
MATERIAL_CONTRACT_TYPES = ("TPA", "PBM", "BROKER", "CONSULTANT")
REQUIRED_FILE_TYPES = ("IN_NETWORK_RATES", "ALLOWED_AMOUNTS")


def round_half_up(value, places=0):
    """ROUND_HALF_UP on an exact rational.  Returns int for places == 0,
    otherwise a Fraction scaled to `places` decimals."""
    frac = Fraction(value)
    scaled = frac * (10 ** places)
    num, den = scaled.numerator, scaled.denominator
    if num >= 0:
        rounded = (2 * num + den) // (2 * den)
    else:
        rounded = -((-2 * num + den) // (2 * den))
    if places == 0:
        return int(rounded)
    return Fraction(rounded, 10 ** places)


def two_dp(value):
    """Round half up to two decimals and hand back a JSON number."""
    return float(round_half_up(value, 2))


def size_multiplier(covered_lives):
    """Covered-lives tier (PRD 3.9)."""
    if covered_lives < 500:
        return Fraction(1, 1)
    if covered_lives <= 4999:
        return Fraction(3, 2)
    return Fraction(2, 1)


def inclusive_days(onset_iso, through_iso):
    """Whole days from onset through the endpoint, INCLUSIVE of both."""
    onset = clock.parse_date(onset_iso)
    through = clock.parse_date(through_iso) if isinstance(through_iso, str) else through_iso
    return (through - onset).days + 1


# ---------------------------------------------------------------------------
# calculations.penalty_accrual_posting
# ---------------------------------------------------------------------------


def price_accrual(deficiency_type, onset_date, clock_date_iso, covered_lives):
    daily_rate = DAILY_RATE_CENTS[deficiency_type]
    multiplier = size_multiplier(covered_lives)
    days_open = inclusive_days(onset_date, clock_date_iso)
    raw_cents = daily_rate * days_open
    signed = min(round_half_up(Fraction(raw_cents) * multiplier), PENALTY_CAP_CENTS)
    return {
        "signed_amount_cents": signed,
        "daily_rate_cents": daily_rate,
        "days_open": days_open,
        "size_multiplier": float(multiplier),
        "onset_date": onset_date,
    }


# ---------------------------------------------------------------------------
# calculations.penalty_exposure_projection  (dual variant, PINNED order)
# ---------------------------------------------------------------------------


def project_exposure(open_deficiencies, as_of_date_iso, end_date_iso, covered_lives):
    """open_deficiencies: list of (deficiency_type, onset_date_iso) already
    filtered so that no onset falls after as_of_date."""
    multiplier = size_multiplier(covered_lives)
    raw_accrued = 0
    raw_statutory = 0
    for deficiency_type, onset in open_deficiencies:
        rate = DAILY_RATE_CENTS[deficiency_type]
        raw_accrued += rate * inclusive_days(onset, as_of_date_iso)
        raw_statutory += rate * inclusive_days(onset, end_date_iso)
    accrued = min(round_half_up(Fraction(raw_accrued) * multiplier), PENALTY_CAP_CENTS)
    statutory = min(round_half_up(Fraction(raw_statutory) * multiplier), PENALTY_CAP_CENTS)
    return {
        "statutory_maximum_cents": statutory,
        "accrued_to_date_cents": accrued,
        "open_deficiency_count": len(open_deficiencies),
        "size_multiplier": float(multiplier),
    }


# ---------------------------------------------------------------------------
# calculations.compensation_reasonableness_score  (PINNED: round per component)
# ---------------------------------------------------------------------------


def compensation_score(contract_type, disclosure):
    if contract_type == "BROKER":
        variant = "TOTAL_WITH_INDIRECT"
        base = disclosure["direct_comp_cents"] + disclosure["indirect_comp_cents"]
    else:
        variant = "DIRECT_ONLY"
        base = disclosure["direct_comp_cents"]

    price_ratio = Fraction(base, disclosure["benchmark_median_cents"])
    if price_ratio > RATIO_CAP:
        price_ratio = RATIO_CAP

    component_price = round_half_up(Fraction(W_PRICE) * price_ratio, 2)
    component_scope = round_half_up(
        Fraction(W_SCOPE * (5 - disclosure["services_scope_score"]), 3), 2
    )
    component_disclosure = round_half_up(
        Fraction(W_DISCLOSURE * (5 - disclosure["disclosure_completeness_score"]), 3), 2
    )
    total = component_price + component_scope + component_disclosure
    status = "UNREASONABLE" if total >= UNREASONABLE_THRESHOLD else "REASONABLE"
    return {
        "variant_applied": variant,
        "component_price_score": float(component_price),
        "component_scope_score": float(component_scope),
        "component_disclosure_score": float(component_disclosure),
        "unreasonableness_score": float(total),
        "status": status,
    }


# ---------------------------------------------------------------------------
# calculations.tool_monthly_uptime
# ---------------------------------------------------------------------------


def monthly_uptime(evaluation_month, outage_windows, target_pct):
    month_start, month_end = clock.month_bounds(evaluation_month)
    month_minutes = clock.days_in_month(evaluation_month) * MINUTES_PER_DAY

    clipped = []
    for window in outage_windows:
        start = clock.parse_datetime(window["window_start"])
        end = clock.parse_datetime(window["window_end"])
        start = max(start, month_start)
        end = min(end, month_end)
        if end > start:
            clipped.append((start, end))
    clipped.sort(key=lambda pair: (pair[0], pair[1]))

    merged = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    total_seconds = sum(int((end - start).total_seconds()) for start, end in merged)
    downtime_minutes = round_half_up(Fraction(total_seconds, 60))
    uptime = round_half_up(
        Fraction(100 * (month_minutes - downtime_minutes), month_minutes), 2
    )
    breached = uptime < Fraction(str(target_pct))
    return {
        "last_downtime_minutes": downtime_minutes,
        "last_uptime_pct": float(uptime),
        "breached": breached,
    }


# ---------------------------------------------------------------------------
# calculations.rxdc_reconciliation_totals  (PINNED: tier keyed on GROSS spend)
# ---------------------------------------------------------------------------


def rebate_cap_tier(gross_spend_cents):
    if gross_spend_cents < 10000000:
        return Fraction(1, 4)
    if gross_spend_cents < 100000000:
        return Fraction(1, 5)
    return Fraction(3, 20)


def rxdc_totals(validated_packages):
    gross = sum(p["plan_paid_cents"] for p in validated_packages) + sum(
        p["member_paid_cents"] for p in validated_packages
    )
    reported = sum(p["rebate_cents"] for p in validated_packages)
    cap_pct = rebate_cap_tier(gross)
    capped = round_half_up(cap_pct * Fraction(gross))
    credit = min(reported, capped)
    return {
        "gross_spend_cents": gross,
        "rebate_reported_cents": reported,
        "rebate_cap_pct": float(cap_pct),
        "rebate_credit_cents": credit,
        "net_plan_spend_cents": gross - credit,
    }


# ---------------------------------------------------------------------------
# calculations.remediation_abatement_amount
# ---------------------------------------------------------------------------


def abatement_amount(accrual_base_cents):
    return round_half_up(ABATEMENT_PCT * Fraction(accrual_base_cents))


# ---------------------------------------------------------------------------
# calculations.refresh_cycle_outcome
# ---------------------------------------------------------------------------


def refresh_deadline(period_end_iso):
    period_end = clock.parse_date(period_end_iso)
    return clock.end_of_day_ms(clock.plus_days(period_end, GRACE_DAYS))


# ---------------------------------------------------------------------------
# calculations.plan_year_compliance_posture — the ladder
# ---------------------------------------------------------------------------


def posture_for(points, freeze_flag):
    if freeze_flag or points >= FROZEN_POINT_THRESHOLD:
        return "FROZEN"
    if points >= DEFICIENT_POINT_THRESHOLD:
        return "DEFICIENT"
    if points >= 1:
        return "AT_RISK"
    return "COMPLIANT"
