"""Pure calculation routines from SCAFFOLD §1.3.

Each function operates on plain values; the caller is responsible for fetching
inputs from the store and writing results back.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from .store import NATIONAL_AVG_BAH
from .util import (
    days_between,
    days_in_month,
    floor_to_cent,
    month_bounds,
    round_half_up,
    to_utc,
)


# ---------- Post-9/11 tier ----------

def post_911_tier(duty_days: int) -> int:
    d = int(duty_days)
    if d < 90:
        return 0
    if d < 180:
        return 40
    if d < 365:
        return 50
    if d < 547:
        return 60
    if d < 730:
        return 70
    if d < 913:
        return 80
    if d < 1095:
        return 90
    return 100


# ---------- Combined rating ----------

def combined_rating(granted_ratings_with_ids: Iterable[tuple[int, str]]) -> int:
    """Compute Veteran.combined_rating.

    Input: iterable of (granted_rating, claim_id) pairs over GRANTED claims.
    Process descending by rating value, tie-broken by ascending claim_id.
    Apply the VA combined-rating formula, then round half-up to a whole percent,
    then round half-up to the nearest 10, clamp [0,100].
    """
    items = list(granted_ratings_with_ids)
    if not items:
        return 0
    items.sort(key=lambda t: (-t[0], t[1]))

    remaining = Decimal("1.0")
    for r, _id in items:
        factor = Decimal("1") - Decimal(r) / Decimal("100")
        remaining = remaining * factor

    raw = (Decimal("1") - remaining) * Decimal("100")
    # Round to nearest whole percent (half-up).
    whole = int(round_half_up(raw, 0))
    # Round whole/10 to nearest integer (half-up), multiply by 10.
    tens_raw = Decimal(whole) / Decimal("10")
    tens = int(round_half_up(tens_raw, 0)) * 10
    return max(0, min(100, tens))


# ---------- Tuition payable ----------

PROGRAM_MAX_PER_TERM: dict[str, Decimal] = {
    "PUBLIC_IN_STATE": Decimal("100000.00"),
    "PRIVATE_NATIONAL": Decimal("13041.34"),
    "FOREIGN": Decimal("13041.34"),
    "VOC_TECH": Decimal("6520.67"),
}


def tuition_payable(tuition_charged: Decimal, program_type: str, tier_pct: int) -> Decimal:
    cap = PROGRAM_MAX_PER_TERM[program_type]
    base = min(Decimal(tuition_charged), cap)
    raw = base * (Decimal(tier_pct) / Decimal("100"))
    return round_half_up(raw, 2)


# ---------- Yellow Ribbon ----------

def yellow_ribbon(
    tuition_charged: Decimal,
    program_type: str,
    school_max_per_year: Decimal,
    tier_pct: int,
) -> dict:
    """Return waterfall: tuition_gap, school_contribution, va_match, student_resp."""
    cap = PROGRAM_MAX_PER_TERM[program_type]
    gap = Decimal(tuition_charged) - cap
    if gap < 0:
        gap = Decimal("0")
    tuition_gap = round_half_up(gap, 2)

    if int(tier_pct) < 100:
        return {
            "tuition_gap": tuition_gap,
            "school_contribution": Decimal("0.00"),
            "va_match": Decimal("0.00"),
            "student_responsibility": round_half_up(tuition_gap, 2),
        }

    half_gap = floor_to_cent(tuition_gap / Decimal("2"))
    school_contribution = min(Decimal(school_max_per_year), half_gap)
    if school_contribution < 0:
        school_contribution = Decimal("0.00")
    va_match = school_contribution
    student_resp = round_half_up(tuition_gap - school_contribution - va_match, 2)
    return {
        "tuition_gap": round_half_up(tuition_gap, 2),
        "school_contribution": round_half_up(school_contribution, 2),
        "va_match": round_half_up(va_match, 2),
        "student_responsibility": student_resp,
    }


# ---------- Voc Rehab subsistence ----------

VOC_REHAB_BASE: dict[str, Decimal] = {
    "FULL_TIME_INSTITUTIONAL": Decimal("883.00"),
    "THREE_QUARTER_INSTITUTIONAL": Decimal("662.00"),
    "HALF_TIME_INSTITUTIONAL": Decimal("441.00"),
    "FARM_COOP": Decimal("772.00"),
    "NON_PAY_OJT": Decimal("0.00"),
}


def voc_rehab_subsistence(training_mode: str, active_dep_count: int) -> Decimal:
    base = VOC_REHAB_BASE[training_mode]
    if active_dep_count <= 2:
        uplift = Decimal("0.00")
    else:
        uplift = Decimal("65.00") * Decimal(active_dep_count - 2)
    return round_half_up(base + uplift, 2)


# ---------- Entitlement consumption ----------

def months_for_enrollment(
    enrollment: dict,
    *,
    now: datetime,
    treat_as_full_term: bool = False,
) -> Decimal:
    """Compute months consumed by a single enrollment under chronological rules.

    When status == COMPLETED, the time window is the entire [term_start, term_end).
    When status == WITHDRAWN, the window is [term_start, min(now, term_end)).
    When projecting (treat_as_full_term=True), use the full term irrespective
    of status — used by the forward-looking projection.
    """
    term_start = to_utc(datetime.fromisoformat(enrollment["term_start"].replace("Z", "+00:00")))
    term_end = to_utc(datetime.fromisoformat(enrollment["term_end"].replace("Z", "+00:00")))

    if treat_as_full_term or enrollment["status"] == "COMPLETED":
        days = days_between(term_start, term_end)
    elif enrollment["status"] == "WITHDRAWN":
        end_used = min(to_utc(now), term_end)
        if end_used < term_start:
            end_used = term_start
        days = days_between(term_start, end_used)
    else:
        # Default: full-term math (used by tentative checks).
        days = days_between(term_start, term_end)

    if days < 0:
        days = 0
    raw = Decimal(days) / Decimal("30")
    return round_half_up(raw, 2)


def entitlement_used_chronological(
    enrollments: list[dict], *, now: datetime
) -> Decimal:
    """Sum months_for_enrollment over COMPLETED/WITHDRAWN, cap 36.00."""
    eligible = [e for e in enrollments if e["status"] in ("COMPLETED", "WITHDRAWN")]
    eligible.sort(key=lambda e: e["term_start"])
    total = Decimal("0")
    for e in eligible:
        total += months_for_enrollment(e, now=now)
    capped = min(Decimal("36.00"), total)
    return round_half_up(capped, 2)


def entitlement_projection(enrollments: list[dict], *, now: datetime) -> Decimal:
    eligible = [
        e
        for e in enrollments
        if e["status"] in ("COMPLETED", "WITHDRAWN", "CERTIFIED", "ACTIVE")
    ]
    eligible.sort(key=lambda e: e["term_start"])
    total = Decimal("0")
    for e in eligible:
        if e["status"] in ("CERTIFIED", "ACTIVE"):
            total += months_for_enrollment(e, now=now, treat_as_full_term=True)
        else:
            total += months_for_enrollment(e, now=now)
    capped = min(Decimal("36.00"), total)
    return round_half_up(capped, 2)


# ---------- Housing allowance ----------

TIME_FACTOR: dict[str, Decimal] = {
    "FULL_TIME": Decimal("1.00"),
    "THREE_QUARTER": Decimal("0.80"),
    "HALF_TIME": Decimal("0.50"),
    "LESS_THAN_HALF": Decimal("0.00"),
}


def _dep_uplift(active_count: int) -> Decimal:
    extras = max(0, active_count - 2)
    uplift = Decimal("50.00") * Decimal(extras)
    cap = Decimal("200.00")
    return min(uplift, cap)


def housing_allowance(
    *,
    month_year: str,
    enrollment: dict,
    school: dict,
    veteran: dict,
    active_dep_count_at_month_start: int,
    bah_base: float,
) -> dict:
    """Return {amount: Decimal, computation_basis: str}."""
    year_s, month_s = month_year.split("-", 1)
    year = int(year_s)
    month = int(month_s)

    tier_pct = Decimal(veteran["post_911_eligibility_tier"]) / Decimal("100")
    time_factor = TIME_FACTOR[enrollment["training_time"]]
    uplift = _dep_uplift(active_dep_count_at_month_start)

    if enrollment["delivery_mode"] == "ONLINE_ONLY":
        monthly_rate = Decimal(str(NATIONAL_AVG_BAH)) * Decimal("0.5") + uplift
        basis = "ONLINE_HALF_NATIONAL"
    else:
        monthly_rate = Decimal(str(bah_base)) + uplift
        basis = "IN_PERSON_TIERED"

    # Partial-month proration based on UTC days overlap.
    m_start, m_end = month_bounds(year, month)
    term_start = to_utc(datetime.fromisoformat(enrollment["term_start"].replace("Z", "+00:00")))
    term_end = to_utc(datetime.fromisoformat(enrollment["term_end"].replace("Z", "+00:00")))
    overlap_start = max(term_start, m_start)
    overlap_end = min(term_end, m_end)
    if overlap_end < overlap_start:
        days_in_term = 0
    else:
        days_in_term = days_between(overlap_start, overlap_end)
    dim = days_in_month(year, month)

    if days_in_term < dim:
        proration = Decimal(days_in_term) / Decimal(dim)
        basis = "PRORATED_PARTIAL_MONTH"
    else:
        proration = Decimal("1")

    raw = monthly_rate * tier_pct * time_factor * proration
    amount = round_half_up(raw, 2)
    return {"amount": amount, "computation_basis": basis}


# ---------- Helpers shared with state-machine logic ----------

def utc_age_years(dob_iso: str, on_date: datetime) -> int:
    dob = datetime.fromisoformat(dob_iso.replace("Z", "+00:00"))
    if dob.tzinfo is None:
        dob = dob.replace(tzinfo=timezone.utc)
    on = to_utc(on_date)
    years = on.year - dob.year
    if (on.month, on.day) < (dob.month, dob.day):
        years -= 1
    return years
