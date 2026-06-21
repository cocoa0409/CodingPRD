"""Domain calculations: QC count, PIA, back pay, SSI, child aux, CDR schedule."""
from decimal import Decimal
from datetime import datetime

import db
from services.utils import (
    add_months,
    first_day_of_month,
    months_between,
    round_half_up,
)


# --- Calc constants ---
LOOKBACK_YEARS = 10
RECENT_QC_THRESHOLD = 20
MAX_REQUIRED_TOTAL_QC = 40

BEND1_CENTS = 117400
BEND2_CENTS = 707900
TIER1_RATE = Decimal("0.90")
TIER2_RATE = Decimal("0.32")
TIER3_RATE = Decimal("0.15")
AIME_DIVISOR_CAP = 35

WAITING_PERIOD_MONTHS = 5
MAX_RETROACTIVE_MONTHS_BEFORE_PFD = 12

FBR_CENTS = 94300
RESOURCE_LIMIT_CENTS = 200000
GENERAL_EXCLUSION_CENTS = 2000
STATE_SUPPLEMENT_TABLE = {"CA": 2050, "NY": 8700}

CHILD_RATE = Decimal("0.50")
FAMILY_MAX_MULTIPLIER = Decimal("1.75")

CDR_MONTHS = {"MIE": 18, "MIP": 36, "MINE": 84}


# ---------- QC counting ----------
def required_total_qc(age_at_filing: int) -> int:
    if age_at_filing < 24:
        return 6
    if age_at_filing < 31:
        return (age_at_filing - 20) * 4
    return MAX_REQUIRED_TOTAL_QC


def compute_qc_counts(claimant_id: str, filing_year: int) -> tuple[int, int]:
    """Return (total_qc_at_filing, recent_qc_in_lookback)."""
    lookback_start = filing_year - LOOKBACK_YEARS
    total = 0
    recent = 0
    for rec in db.work_credits.values():
        if rec.get("claimant_id") != claimant_id:
            continue
        y = rec.get("year")
        if y is None or y > filing_year:
            continue
        c = rec.get("credits_earned", 0)
        total += c
        if lookback_start <= y <= filing_year:
            recent += c
    return total, recent


# ---------- PIA ----------
def compute_pia_cents(claimant_id: str) -> int:
    """Simplified bend-point AIME -> PIA formula."""
    records = [r for r in db.work_credits.values() if r.get("claimant_id") == claimant_id]
    years_with_credits = [r for r in records if r.get("credits_earned", 0) > 0]
    if not years_with_credits:
        return 0
    n = min(AIME_DIVISOR_CAP, len(years_with_credits))
    # Top N years by earnings_cents desc, tie-break year ASC.
    sorted_recs = sorted(
        years_with_credits,
        key=lambda r: (-r.get("earnings_cents", 0), r.get("year", 0)),
    )
    top_n = sorted_recs[:n]
    total_earnings = sum(r.get("earnings_cents", 0) for r in top_n)
    aime_cents = round_half_up(Decimal(total_earnings) / Decimal(n * 12))

    tier1 = min(aime_cents, BEND1_CENTS)
    tier2 = min(max(0, aime_cents - BEND1_CENTS), BEND2_CENTS - BEND1_CENTS)
    tier3 = max(0, aime_cents - BEND2_CENTS)

    pia = (
        round_half_up(TIER1_RATE * Decimal(tier1))
        + round_half_up(TIER2_RATE * Decimal(tier2))
        + round_half_up(TIER3_RATE * Decimal(tier3))
    )
    return pia


# ---------- Back pay ----------
def compute_back_pay(
    pia_cents: int,
    established_onset_date: datetime,
    protective_filing_date: datetime,
    decision_date: datetime,
) -> int:
    # 5-month waiting period: first day of (month_of(EOD) + 5 months)
    entitlement_start = first_day_of_month(add_months(established_onset_date, WAITING_PERIOD_MONTHS))
    # Retroactive floor: first day of (PFD - 12 months)
    retroactive_floor = first_day_of_month(add_months(protective_filing_date, -MAX_RETROACTIVE_MONTHS_BEFORE_PFD))
    effective_start = max(entitlement_start, retroactive_floor)

    months = months_between(effective_start, decision_date)
    if months < 0:
        months = 0
    return pia_cents * months


def entitlement_start_date(
    established_onset_date: datetime, protective_filing_date: datetime
) -> datetime:
    entitlement = first_day_of_month(add_months(established_onset_date, WAITING_PERIOD_MONTHS))
    retroactive_floor = first_day_of_month(
        add_months(protective_filing_date, -MAX_RETROACTIVE_MONTHS_BEFORE_PFD)
    )
    return max(entitlement, retroactive_floor)


# ---------- SSI supplement ----------
def compute_ssi_supplement(
    claimant: dict, monthly_benefit_cents: int
) -> tuple[str, int, int]:
    """Return (status, monthly_supplement_cents, state_supplement_cents)."""
    resources = claimant.get("countable_resources_cents", 0) or 0
    if resources > RESOURCE_LIMIT_CENTS:
        return "INELIGIBLE_RESOURCES", 0, 0
    income = claimant.get("monthly_income_cents", 0) or 0
    countable_income = max(0, income - GENERAL_EXCLUSION_CENTS)
    monthly = max(0, FBR_CENTS - countable_income - monthly_benefit_cents)
    state_supp = STATE_SUPPLEMENT_TABLE.get(claimant.get("filing_state", ""), 0)
    return "ACTIVE", monthly, state_supp


# ---------- Child auxiliary ----------
def compute_child_aux_base_and_headroom(award: dict) -> tuple[int, int, int]:
    """Return (base_amount_cents, family_max_cents, headroom_cents).

    headroom = family_max - monthly_benefit_cents - sum(active aux amounts on this award)
    """
    pia = award.get("primary_insurance_amount_cents", 0)
    base = round_half_up(Decimal(pia) * CHILD_RATE)
    family_max = round_half_up(Decimal(pia) * FAMILY_MAX_MULTIPLIER)
    existing_total = 0
    # Aggregate ACTIVE auxiliaries in created_at ASC order (deterministic).
    auxes = [
        a
        for a in db.child_aux.values()
        if a.get("benefit_award_id") == award["id"] and a.get("status") == "ACTIVE"
    ]
    auxes.sort(key=lambda a: (a.get("created_at", ""), a.get("id", "")))
    for a in auxes:
        existing_total += a.get("monthly_amount_cents", 0)
    monthly_benefit = award.get("monthly_benefit_cents", 0)
    headroom = family_max - monthly_benefit - existing_total
    return base, family_max, headroom


# ---------- CDR schedule ----------
def cdr_schedule_date(diary: str) -> datetime:
    months = CDR_MONTHS.get(diary, CDR_MONTHS["MIE"])
    return add_months(db.now_utc(), months)
