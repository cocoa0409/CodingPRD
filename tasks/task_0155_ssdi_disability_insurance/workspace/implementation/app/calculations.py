"""Money math + temporal calculations.

Implements the formulas described in SCAFFOLD.yaml §1.3 and PRD §3.5:
  - qc_requirement_lookup  (age-based threshold tiers)
  - pia_calc               (AIME -> PIA bend-point formula, dime-round-down)
  - family_max_calc        (Family Maximum bend-point formula + DIB clamp)
  - back_pay_calc          (months retroactive * monthly_benefit_cents, capped)
  - child_aux_calc         (waterfall allocation across entitled siblings)
  - waiting_period_calc    (5-month statutory wait, next-month anchoring)
  - cdr_diary_lookup       (MIE/MIP/MINE diary intervals)
  - ssi_calc               (FBR minus countable income with stacked exclusions)

All monetary values are integer cents. We avoid float wherever rounding
matters by doing the multiplication on integer cents and dividing with `//`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from typing import List, Tuple

from app.util import add_months, first_day_of_month, floor_age_years, month_diff


# ---------------------------------------------------------------------------
# Constants (mirror SCAFFOLD.yaml §1.3 constants)
# ---------------------------------------------------------------------------

QC_EARNINGS_THRESHOLD_CENTS_BY_YEAR = {
    2024: 173000,   # $1,730 per QC
    2025: 181000,   # $1,810 per QC
}
QC_THRESHOLD_FALLBACK_CENTS = 173000   # default to 2024 threshold for unknown years

YEARLY_CAP_BY_YEAR = {
    2024: 16820000,  # $168,200 Social Security wage base
}
YEARLY_CAP_FALLBACK_CENTS = 16820000

BEND_POINT_1 = 117400   # $1,174 (cents)
BEND_POINT_2 = 707800   # $7,078 (cents)

FMB_BP1 = 150000   # $1,500
FMB_BP2 = 216500   # $2,165
FMB_BP3 = 282500   # $2,825

GENERAL_INCOME_EXCLUSION = 2000   # $20 (cents)
EARNED_INCOME_EXCLUSION = 6500    # $65 (cents)
SSI_RESOURCE_LIMIT_CENTS = 200000   # $2,000 individual

FBR_BY_LIVING_ARRANGEMENT = {
    "OWN_HOUSEHOLD": 96700,
    "ANOTHER_HOUSEHOLD": 64470,
    "INSTITUTION": 3000,
}

WAITING_PERIOD_MONTHS = 5
MAX_PRE_FILING_RETRO_MONTHS = 12
APPEAL_WINDOW_DAYS = 60
CDR_SCHEDULE_LOOKBACK_DAYS = 60

MIE_DIARY_MONTHS = 18
MIP_DIARY_MONTHS = 36
MINE_DIARY_MONTHS = 84


# ---------------------------------------------------------------------------
# QC requirement lookup
# ---------------------------------------------------------------------------

def qc_requirement_lookup(date_of_birth: date, alleged_onset_date: date) -> Tuple[int, int, int]:
    """Return (qc_required, qc_recent_required, recent_window_quarters)."""
    age = floor_age_years(alleged_onset_date, date_of_birth)
    # Fully-insured lifetime QCs
    if age < 24:
        required = 6
    elif age <= 30:
        required = 2 * (age - 21)
    elif age <= 42:
        required = 20
    elif age <= 61:
        required = 20 + (age - 42)
    else:
        required = 40
    # Recent-work test
    if age < 24:
        recent_required = 6
        recent_window = 12
    elif age < 31:
        # ceiling((age - 21) * 2)
        val = (age - 21) * 2
        recent_required = val
        recent_window = val
    else:
        recent_required = 20
        recent_window = 40
    return required, recent_required, recent_window


def qc_threshold_for_year(year: int) -> int:
    return QC_EARNINGS_THRESHOLD_CENTS_BY_YEAR.get(year, QC_THRESHOLD_FALLBACK_CENTS)


def yearly_cap_for_year(year: int) -> int:
    return YEARLY_CAP_BY_YEAR.get(year, YEARLY_CAP_FALLBACK_CENTS)


def compute_qc_aggregates(
    quarter_credits: List[dict],
    alleged_onset_date: date,
    recent_window_quarters: int,
) -> Tuple[int, int, List[dict]]:
    """Compute total_qc_earned (capped 4/year, credited only) and qc_recent_window.

    Returns (total_qc_earned, qc_recent_window, updated_rows). `updated_rows`
    is a list of dicts with computed qc_count + credited flags for each input
    QuarterCredit row; the caller persists these back to the store.
    """
    aod_year = alleged_onset_date.year
    aod_quarter = (alleged_onset_date.month - 1) // 3 + 1

    # Sort the rows so we can apply the per-year cap deterministically by
    # created_at ascending — earlier rows are credited first when more than
    # four quarters of credits accumulate within the same calendar year.
    sorted_rows = sorted(quarter_credits, key=lambda r: (r["created_at"], r["id"]))

    updated_rows: List[dict] = []
    # Tracks how many credits per (year) have already counted toward the cap.
    per_year_count: dict = {}
    total = 0
    recent = 0

    # Convert AOD into a single integer index = year*4 + quarter for window math.
    aod_index = aod_year * 4 + aod_quarter
    window_lower = aod_index - recent_window_quarters + 1   # inclusive lower bound

    for row in sorted_rows:
        year = row["year"]
        quarter = row["quarter"]
        earnings = row["earnings_cents"]
        threshold = qc_threshold_for_year(year)
        qc_count = 1 if earnings >= threshold else 0

        # Lookback window: (year, quarter) must be at or before AOD's quarter.
        idx = year * 4 + quarter
        in_window = window_lower <= idx <= aod_index
        in_lifetime = idx <= aod_index   # quarter at or before AOD

        # Apply the cap of 4 credits per year for the LIFETIME total.
        credited_for_total = False
        if qc_count == 1 and in_lifetime:
            already = per_year_count.get(year, 0)
            if already < 4:
                per_year_count[year] = already + 1
                credited_for_total = True
                total += 1

        # Recent-window count uses the same cap-aware credits.
        if credited_for_total and in_window:
            recent += 1

        new_row = dict(row)
        new_row["qc_count"] = qc_count
        # "credited" is whether this row counted toward the lifetime total
        # (i.e. qc_count==1, within lookback, and not capped).
        new_row["credited"] = credited_for_total
        updated_rows.append(new_row)

    return total, recent, updated_rows


# ---------------------------------------------------------------------------
# Waiting period (5 months) — next-month anchoring
# ---------------------------------------------------------------------------

def waiting_period_calc(eod: date) -> date:
    """entitlement_date = first day of the (eod's anchor month + 5) month."""
    if eod.day == 1:
        anchor = first_day_of_month(eod)
    else:
        anchor = first_day_of_month(add_months(eod, 1))
    return add_months(anchor, WAITING_PERIOD_MONTHS)


# ---------------------------------------------------------------------------
# PIA / AIME computation
# ---------------------------------------------------------------------------

def _build_yearly_earnings(
    quarter_credits: List[dict],
    alleged_onset_date: date,
    variant: str,
) -> dict:
    """Roll up QuarterCredit rows into yearly earnings totals, capped per year.

    variant="PROVISIONAL": for AOD year, only include quarters with
      quarter <= last completed quarter (i.e. truncate partial future quarters).
    variant="FINAL": include the full year-of-AOD earnings, no truncation.
    """
    aod_year = alleged_onset_date.year
    aod_quarter = (alleged_onset_date.month - 1) // 3 + 1

    totals: dict = {}
    for row in quarter_credits:
        year = row["year"]
        quarter = row["quarter"]
        if year == aod_year and variant == "PROVISIONAL":
            # Keep only fully-completed quarters at or before AOD quarter.
            if quarter > aod_quarter:
                continue
        totals[year] = totals.get(year, 0) + row["earnings_cents"]

    # Cap each year at the wage base.
    capped = {}
    for year, total in totals.items():
        cap = yearly_cap_for_year(year)
        capped[year] = min(total, cap)
    return capped


def pia_calc(
    quarter_credits: List[dict],
    alleged_onset_date: date,
    variant: str = "PROVISIONAL",
) -> Tuple[int, int]:
    """Return (aime_cents, pia_cents) for the supplied earnings ledger.

    AIME = sum of the highest-35 annual earnings divided by 420 months,
    then the PIA bend-point formula and dime-round-down.
    """
    capped = _build_yearly_earnings(quarter_credits, alleged_onset_date, variant)
    annuals = sorted(capped.values(), reverse=True)
    top35 = annuals[:35]
    sum_top35 = sum(top35)
    # AIME in cents — integer division by 420 months.
    aime = sum_top35 // 420

    # Bend-point formula. Use Decimal to avoid float drift on 0.32 / 0.15.
    band1 = Decimal("0.90") * Decimal(min(aime, BEND_POINT_1))
    band2 = Decimal("0.32") * Decimal(max(0, min(aime, BEND_POINT_2) - BEND_POINT_1))
    band3 = Decimal("0.15") * Decimal(max(0, aime - BEND_POINT_2))
    raw = (band1 + band2 + band3).to_integral_value(rounding=ROUND_FLOOR)
    pia = int(raw)
    # Dime-round-down
    pia = (pia // 10) * 10
    return aime, pia


# ---------------------------------------------------------------------------
# Family Maximum + waterfall
# ---------------------------------------------------------------------------

def family_max_calc(pia_cents: int) -> int:
    """Family Maximum cents from PIA: bend-point + DIB clamp."""
    band1 = Decimal("1.50") * Decimal(min(pia_cents, FMB_BP1))
    band2 = Decimal("2.72") * Decimal(max(0, min(pia_cents, FMB_BP2) - FMB_BP1))
    band3 = Decimal("1.34") * Decimal(max(0, min(pia_cents, FMB_BP3) - FMB_BP2))
    band4 = Decimal("1.75") * Decimal(max(0, pia_cents - FMB_BP3))
    raw = (band1 + band2 + band3 + band4).to_integral_value(rounding=ROUND_FLOOR)
    fmb = int(raw)
    fmb = (fmb // 10) * 10   # dime-round-down

    # DIB clamp: 1.50 * pia <= fmb <= 1.85 * pia
    floor_cents = int((Decimal("1.50") * Decimal(pia_cents)).to_integral_value(rounding=ROUND_FLOOR))
    ceiling_cents = int((Decimal("1.85") * Decimal(pia_cents)).to_integral_value(rounding=ROUND_FLOOR))
    if fmb < floor_cents:
        fmb = floor_cents
    if fmb > ceiling_cents:
        fmb = ceiling_cents
    return fmb


def child_aux_waterfall(
    pia_cents: int,
    family_max_cents: int,
    entitled_children: List[dict],
) -> dict:
    """Return a {child_id: monthly_benefit_cents} mapping.

    entitled_children: list of dicts with at least id, child_date_of_birth, created_at.
    Children must be sorted by (date_of_birth ASC, created_at ASC) for tie-breaks.
    """
    n = len(entitled_children)
    if n == 0:
        return {}

    gross = (pia_cents * 50) // 100   # floor(0.5 * pia_cents) via integer math
    pool = max(0, family_max_cents - pia_cents)

    if n * gross <= pool:
        return {c["id"]: gross for c in entitled_children}

    each = pool // n if n > 0 else 0
    remainder = pool - each * n

    # Order: child_date_of_birth ASC (oldest first), tie-break by created_at ASC.
    ordered = sorted(
        entitled_children,
        key=lambda c: (c["child_date_of_birth"], c["created_at"], c["id"]),
    )

    result = {}
    for idx, c in enumerate(ordered):
        if idx < remainder:
            result[c["id"]] = each + 1
        else:
            result[c["id"]] = each
    return result


# ---------------------------------------------------------------------------
# Back pay
# ---------------------------------------------------------------------------

def back_pay_calc(
    entitlement_date: date,
    approval_date: date,
    filing_date: date,
    monthly_benefit_cents: int,
    variant: str = "PROVISIONAL",
) -> int:
    """Return back_pay_cents.

    Months retroactive = month_diff(approval_month, entitlement_date),
    capped by the variant-specific pre-filing retro rule.
    """
    if isinstance(approval_date, datetime):
        approval_date = approval_date.date()

    # months from entitlement through the month immediately before approval (exclusive).
    raw_months = month_diff(approval_date, entitlement_date)
    if raw_months <= 0:
        return 0

    # Split into pre-filing months and post-filing months.
    if entitlement_date >= filing_date:
        pre_filing_months = 0
        post_filing_months = raw_months
    else:
        pre_filing_months = max(0, month_diff(filing_date, entitlement_date))
        post_filing_months = raw_months - pre_filing_months
        post_filing_months = max(0, post_filing_months)

    if variant == "PROVISIONAL":
        allowed_pre = min(MAX_PRE_FILING_RETRO_MONTHS, pre_filing_months)
    elif variant == "FINAL":
        allowed_pre = min(MAX_PRE_FILING_RETRO_MONTHS, pre_filing_months)
    else:
        allowed_pre = pre_filing_months

    total_months = allowed_pre + post_filing_months
    if total_months < 0:
        total_months = 0
    return total_months * monthly_benefit_cents


# ---------------------------------------------------------------------------
# CDR diary lookup
# ---------------------------------------------------------------------------

def cdr_diary_lookup(
    medical_basis: str,
    listing_code: str | None,
    age_category_at_decision: str | None,
) -> Tuple[str, int]:
    """Return (cdr_diary, diary_months) per SCAFFOLD.yaml §1.3."""
    if medical_basis == "MEETS_LISTING":
        if listing_code and (listing_code.startswith("1.") or listing_code.startswith("11.")):
            return "MIP", MIP_DIARY_MONTHS
        return "MINE", MINE_DIARY_MONTHS
    if medical_basis == "EQUALS_LISTING":
        return "MIE", MIE_DIARY_MONTHS
    if medical_basis == "DISABLED_BY_RFC":
        if age_category_at_decision == "ADVANCED":
            return "MINE", MINE_DIARY_MONTHS
        return "MIP", MIP_DIARY_MONTHS
    # Fallback (should be impossible on an ALLOW path)
    return "MIP", MIP_DIARY_MONTHS


# ---------------------------------------------------------------------------
# SSI calculation
# ---------------------------------------------------------------------------

def ssi_calc(
    countable_income_cents: int,
    living_arrangement: str,
    earned_income_cents: int | None = None,
    unearned_income_cents: int | None = None,
) -> int:
    """Compute ssi_payment_cents.

    The PRD allows `countable_income_cents` to be a single composite figure;
    when callers don't split into earned vs unearned, we treat the entire
    figure as unearned. The exclusions then apply per PRD §3.5: the $20
    general exclusion is taken from unearned income first, with any unused
    portion spilling over into the $65 earned-income exclusion, after which
    half of the remaining earned income is countable.
    """
    if earned_income_cents is None and unearned_income_cents is None:
        unearned_income_cents = max(0, int(countable_income_cents))
        earned_income_cents = 0
    earned = max(0, int(earned_income_cents or 0))
    unearned = max(0, int(unearned_income_cents or 0))

    excluded_unearned = min(unearned, GENERAL_INCOME_EXCLUSION)
    remaining_unearned = unearned - excluded_unearned
    spillover = GENERAL_INCOME_EXCLUSION - excluded_unearned
    earned_exclusion_total = spillover + EARNED_INCOME_EXCLUSION
    remaining_earned = max(0, earned - earned_exclusion_total)
    countable_earned_after_half = remaining_earned // 2
    countable_income = remaining_unearned + countable_earned_after_half

    fbr = FBR_BY_LIVING_ARRANGEMENT.get(living_arrangement, 0)
    return max(0, fbr - countable_income)
