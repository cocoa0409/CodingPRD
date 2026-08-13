"""Calculation rules (scaffold §1.3 / PRD §3).

Every formula is implemented with Decimal arithmetic and ROUND_HALF_UP,
exactly once per prescribed rounding step. Input-set discipline:
  FINAL       -> ACCEPTED contribution lines only
  PROVISIONAL -> ACCEPTED + PENDING lines (REJECTED excluded)
"""

from datetime import timedelta
from decimal import Decimal

from db import store, now
from utils import (
    dec,
    round_half_up_int,
    round_half_up_2dp,
    age_completed,
    age_diff_completed,
    add_years,
    whole_months_between,
    first_of_month,
    add_months_first_of_month,
)

# Constants from the scaffold calculations table
FAS_YEARS = 3
MONTHS_PER_YEAR = 12
TIER_25_MULT = Decimal("0.025")
TIER_20_MULT = Decimal("0.022")
TIER_10_MULT = Decimal("0.020")
BASE_MULT = Decimal("0.017")
FLAT_RATE_PCT = Decimal("0.10")
FLAT_WINDOW_YEARS = 5
RETIREMENT_AGE = 60
AGE_FACTOR_HI = Decimal("0.35")
AGE_FACTOR_MID = Decimal("0.28")
AGE_FACTOR_LO = Decimal("0.22")
QUOTE_TTL_DAYS = 90
DISABILITY_FAS_PCT = Decimal("0.60")
COLA_MIN_MONTHS_ACTIVE = 12
VESTING_YEARS = Decimal("5")
RETIREMENT_AGE_GATE = 60
APPEAL_WINDOW_DAYS = 60
CLAIM_WINDOW_DAYS = 365


def member_lines(member_id, statuses):
    return [
        l
        for l in store.lines.values()
        if l["member_id"] == member_id and l["status"] in statuses
    ]


def member_purchases(member_id, statuses=None):
    return [
        p
        for p in store.purchases.values()
        if p["member_id"] == member_id and (statuses is None or p["status"] in statuses)
    ]


def member_benefits(member_id):
    out = [b for b in store.benefits.values() if b["member_id"] == member_id]
    out.sort(key=lambda b: b["_seq"])
    return out


def member_retirement_apps(member_id):
    return [a for a in store.retirement_apps.values() if a["member_id"] == member_id]


def member_disability_apps(member_id):
    return [a for a in store.disability_apps.values() if a["member_id"] == member_id]


# ---------------------------------------------------------------------------
# member_service_accrual
# ---------------------------------------------------------------------------

def service_years(member_id, variant="FINAL"):
    """round_half_up(sum(service_months of included lines)/12
       + sum(years_purchased of COMPLETED purchases), 2)."""
    statuses = ("ACCEPTED",) if variant == "FINAL" else ("ACCEPTED", "PENDING")
    months = sum(l["service_months"] for l in member_lines(member_id, statuses))
    purchased = sum(
        (dec(p["years_purchased"]) for p in member_purchases(member_id, ("COMPLETED",))),
        Decimal("0"),
    )
    total = Decimal(months) / Decimal(MONTHS_PER_YEAR) + purchased
    return round_half_up_2dp(total)


def current_salary_cents(member_id):
    """period_salary_cents of the ACCEPTED line with the highest fiscal_year;
    ties broken by latest created_at (creation order as final tiebreak);
    None when the member has no ACCEPTED line."""
    lines = member_lines(member_id, ("ACCEPTED",))
    if not lines:
        return None
    best = max(lines, key=lambda l: (l["fiscal_year"], l["created_at"], l["_seq"]))
    return best["period_salary_cents"]


def recompute_member(member):
    """Full recompute-on-event of the member's derived aggregates (§2.9).
    Returns True when a stored value changed."""
    new_years = service_years(member["id"], "FINAL")
    new_salary = current_salary_cents(member["id"])
    changed = (
        new_years != dec(member["total_service_years"])
        or new_salary != member["current_annual_salary_cents"]
    )
    member["total_service_years"] = new_years
    member["current_annual_salary_cents"] = new_salary
    return changed


# ---------------------------------------------------------------------------
# final_average_salary
# ---------------------------------------------------------------------------

def fas_cents(member_id, variant="FINAL"):
    """Average period_salary over the member's top-3 included fiscal years
    (ranked desc), dividing by the number of distinct years taken."""
    statuses = ("ACCEPTED",) if variant == "FINAL" else ("ACCEPTED", "PENDING")
    lines = member_lines(member_id, statuses)
    years = sorted({l["fiscal_year"] for l in lines}, reverse=True)[:FAS_YEARS]
    if not years:
        return 0
    total = sum(l["period_salary_cents"] for l in lines if l["fiscal_year"] in years)
    return round_half_up_int(Decimal(total) / Decimal(len(years)))


# ---------------------------------------------------------------------------
# benefit_estimate
# ---------------------------------------------------------------------------

def multiplier_for(service):
    if service >= 25:
        return TIER_25_MULT
    if service >= 20:
        return TIER_20_MULT
    if service >= 10:
        return TIER_10_MULT
    return BASE_MULT


def option_factor(option_election, age_diff):
    if option_election == "JOINT_50":
        return Decimal("0.95") if age_diff <= 10 else Decimal("0.90")
    if option_election == "JOINT_100":
        return Decimal("0.90") if age_diff <= 10 else Decimal("0.82")
    return Decimal("1.00")


def benefit_estimate(member, variant="FINAL", option_election="SINGLE_LIFE",
                     beneficiary_dob=None):
    """Single final rounding: round_half_up(fas * mult * service / 12 * factor)."""
    fas = fas_cents(member["id"], variant)
    svc = service_years(member["id"], variant)
    mult = multiplier_for(svc)
    if beneficiary_dob is not None:
        age_diff = age_diff_completed(member["_dob"], beneficiary_dob)
    else:
        age_diff = 0
    factor = option_factor(option_election, age_diff)
    base_monthly = Decimal(fas) * mult * svc / Decimal(MONTHS_PER_YEAR)
    monthly = round_half_up_int(base_monthly * factor)
    return {
        "fas_cents": fas,
        "service_years": svc,
        "multiplier": mult,
        "monthly_cents": monthly,
    }


# ---------------------------------------------------------------------------
# service_purchase_cost
# ---------------------------------------------------------------------------

def purchase_quote(member, years_purchased):
    """Compute both variants; select FLAT when the quote date is within 5
    years of hire_date, else ACTUARIAL. Returns (flat, actuarial, variant,
    quoted, expires_at_datetime)."""
    salary = member["current_annual_salary_cents"]
    years = dec(years_purchased)
    flat = round_half_up_int(FLAT_RATE_PCT * Decimal(salary) * years)

    age = age_completed(member["_dob"], now().date())
    years_to_60 = RETIREMENT_AGE - age
    if years_to_60 >= 10:
        age_factor = AGE_FACTOR_HI
    elif years_to_60 >= 5:
        age_factor = AGE_FACTOR_MID
    else:
        age_factor = AGE_FACTOR_LO
    actuarial = round_half_up_int(Decimal(salary) * years * age_factor)

    if add_years(member["_hire_date"], FLAT_WINDOW_YEARS) >= now().date():
        variant = "FLAT"
    else:
        variant = "ACTUARIAL"
    quoted = flat if variant == "FLAT" else actuarial
    expires_at = now() + timedelta(days=QUOTE_TTL_DAYS)
    return flat, actuarial, variant, quoted, expires_at


# ---------------------------------------------------------------------------
# installment_schedule (pinned rounding: round each of the first N-1, the
# remainder — possibly larger — lands on the final payment)
# ---------------------------------------------------------------------------

def installment_amounts(quoted_cost_cents, installment_count):
    per = round_half_up_int(Decimal(quoted_cost_cents) / Decimal(installment_count))
    amounts = [per] * (installment_count - 1)
    amounts.append(quoted_cost_cents - per * (installment_count - 1))
    return amounts


def installment_due_date(accept_dt, sequence_number):
    """First day of the month that is sequence_number months after the
    accept month (sequence 1 -> first of the following month)."""
    return add_months_first_of_month(accept_dt.year, accept_dt.month, sequence_number)


# ---------------------------------------------------------------------------
# cola_application
# ---------------------------------------------------------------------------

def cola_months_active(benefit, on_date):
    return whole_months_between(benefit["_effective_date"], on_date)


def cola_adjusted_amount(monthly_amount_cents, cola_rate_pct):
    return round_half_up_int(
        Decimal(monthly_amount_cents) * (Decimal("1") + dec(cola_rate_pct))
    )


# ---------------------------------------------------------------------------
# disability_benefit / survivor_benefit
# ---------------------------------------------------------------------------

def disability_monthly_cents(member_id):
    fas = fas_cents(member_id, "FINAL")
    return round_half_up_int(Decimal(fas) * DISABILITY_FAS_PCT / Decimal(12))


def survivor_monthly_cents(terminated_benefit):
    opt = terminated_benefit.get("_origin_option")
    pct = Decimal("0.50") if opt == "JOINT_50" else Decimal("1.00")
    return round_half_up_int(Decimal(terminated_benefit["monthly_amount_cents"]) * pct)
