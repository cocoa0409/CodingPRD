"""Domain calculations: FPL%, CSR tier, APTC estimated, premium, etc."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import db
from .constants import (
    fpl_denominator,
    fpl_version_for_year,
    applicable_percentage,
    age_multiplier,
    TOBACCO_SURCHARGE,
    MEDICAID_EXPANSION,
)
from .dates import (
    parse_iso_date,
    years_between,
    iso_date_str,
    first_day_of_next_month,
    first_of_month,
)
from .money import half_up_int, half_up_one_decimal


# -- household composition rollups --

def household_members_for(app_id: str) -> list:
    return [m for m in db.household_members.values() if m["application_id"] == app_id]


def income_records_for_member(member_id: str) -> list:
    return [r for r in db.income_records.values() if r["member_id"] == member_id]


def compute_member_magi_cents(member_id: str) -> int:
    """Sum un-superseded IncomeRecord rows for this member."""
    total = 0
    for r in db.income_records.values():
        if r["member_id"] != member_id:
            continue
        if r.get("superseded_by_id"):
            continue
        total += r["amount_cents"]
    return total


def update_member_magi(member: dict) -> None:
    member["member_magi_cents"] = compute_member_magi_cents(member["id"])


def compute_household_size(app_id: str) -> int:
    return sum(1 for m in household_members_for(app_id) if m["include_in_household"])


def compute_total_magi_cents(app_id: str) -> int:
    total = 0
    members = household_members_for(app_id)
    for m in members:
        if not m["include_in_magi"]:
            continue
        for r in db.income_records.values():
            if r["member_id"] != m["id"]:
                continue
            if r.get("superseded_by_id"):
                continue
            total += r["amount_cents"]
    return total


def compute_fpl_percentage(total_magi_cents: int, household_size: int, fpl_version: str) -> float:
    """Return fpl_percentage rounded half-up to 1 decimal place."""
    if household_size < 1:
        household_size = 1
    denom = fpl_denominator(fpl_version, household_size)
    if denom <= 0:
        return 0.0
    # (total_magi / denom) * 100 — use Decimal for precision
    raw = (Decimal(total_magi_cents) / Decimal(denom)) * Decimal(100)
    q = raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


# -- CSR tier classification --

def classify_csr(fpl_pct: float) -> str:
    """Return CSR tier per fpl_percentage half-open intervals (1-decimal precision)."""
    if fpl_pct < 100.0:
        return "NONE"
    elif 100.0 <= fpl_pct < 138.0:
        return "CSR_PLUS"
    elif 138.0 <= fpl_pct < 150.0:
        return "CSR_94"
    elif 150.0 <= fpl_pct < 200.0:
        return "CSR_87"
    elif 200.0 <= fpl_pct < 250.0:
        return "CSR_73"
    else:
        return "NONE"


# -- Medicaid eligibility --

def medicaid_eligible_for_member(member: dict, app: dict) -> bool:
    """Determine whether a member is Medicaid eligible per state, age, FPL%."""
    coverage_year = app["coverage_year"]
    coverage_year_start = date(coverage_year, 1, 1)
    dob = parse_iso_date(member["date_of_birth"])
    age = years_between(dob, coverage_year_start)
    state_expanded = MEDICAID_EXPANSION.get(app["filing_state"], False)
    fpl_pct = app.get("fpl_percentage") or 0.0

    if age < 19:
        return fpl_pct < 200.0
    if age >= 65:
        return False
    if state_expanded:
        return fpl_pct < 138.0
    return fpl_pct < 50.0


# -- Benchmark Silver lookup --

def find_benchmark_silver(filing_state: str, coverage_year: int):
    """Return the active benchmark Silver plan for (filing_state, coverage_year), or None."""
    for p in db.plans.values():
        if (
            p["filing_state"] == filing_state
            and p["coverage_year"] == coverage_year
            and p["is_benchmark_silver"]
            and p["status"] == "ACTIVE"
        ):
            return p
    return None


# -- Age-adjusted premium per member --

def age_adjusted_premium_for_member(member: dict, plan: dict, reference_date: date) -> int:
    """Compute per-member monthly premium in cents (rounded half-up to cent)."""
    dob = parse_iso_date(member["date_of_birth"])
    age = years_between(dob, reference_date)
    mult = age_multiplier(age)
    base = plan["base_monthly_premium_cents"]
    per_member = half_up_int(Decimal(base) * Decimal(str(mult)))
    if member.get("is_tobacco_user") and age >= 21:
        per_member = half_up_int(Decimal(per_member) * Decimal(str(TOBACCO_SURCHARGE)))
    return per_member


def monthly_premium_for_plan(plan: dict, members: list, coverage_start: date) -> int:
    """Sum per-member rounded premiums (per-member round, then sum)."""
    total = 0
    for m in members:
        if not m["include_in_household"]:
            continue
        total += age_adjusted_premium_for_member(m, plan, coverage_start)
    return total


# -- APTC estimated --

def compute_aptc_estimated(app: dict, members: list) -> int:
    """Compute aptc_estimated_cents (forward-looking)."""
    fpl_pct = app.get("fpl_percentage") or 0.0
    total_magi = app.get("total_magi_cents") or 0

    # Below 100% FPL — Medicaid territory: no APTC
    if fpl_pct < 100.0:
        return 0

    benchmark = find_benchmark_silver(app["filing_state"], app["coverage_year"])
    if benchmark is None:
        return 0  # caller validated separately

    # Applicable percentage at given fpl_pct
    fraction = applicable_percentage(fpl_pct)
    # Above 400% — fraction = 1.0000 collapses to no subsidy
    if fraction >= 1.0:
        return 0

    expected_contribution = half_up_int(Decimal(total_magi) * Decimal(str(fraction)))

    # Annual benchmark premium: monthly age-adjusted * 12 for all included members.
    # Use the start of the coverage year as the reference date (forward-looking).
    reference_date = date(app["coverage_year"], 1, 1)
    monthly_benchmark = monthly_premium_for_plan(benchmark, members, reference_date)
    annual_benchmark = monthly_benchmark * 12

    aptc_annual = annual_benchmark - expected_contribution
    return max(0, aptc_annual)
