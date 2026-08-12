"""Calculation rules (SCAFFOLD §1.3). Integer cents, round-half-up at pinned stages."""
from decimal import Decimal

import domain
import errors
from domain import (
    CLASS_MULT, MODE_FACTOR, MODE_MONTHS, LOAN_ANNUAL_INTEREST_RATE_BPS,
    REINSTATEMENT_ANNUAL_RATE,
)
from util import dec, round_half_up, age_years, add_months, add_years_365


def modal_premium(face_cents, base_rate, uw_class, extra_bps, mode):
    """modal_premium_at_issue: round monthly rate first, then multiply by mode
    factor, then round again. Pinned rounding order (PRD §3.3)."""
    mult = dec(CLASS_MULT[uw_class])
    extra = Decimal(1) + dec(extra_bps) / dec(10000)
    monthly_raw = (dec(face_cents) / dec(100000)) * dec(base_rate) * mult * extra / dec(100)
    monthly_rate = round_half_up(monthly_raw)
    modal = round_half_up(dec(monthly_rate) * dec(MODE_FACTOR[mode]))
    return modal


def coi_lookup_rate(coi_rate_table, attained_age):
    """Largest attained_age key <= attained_age; if above all keys, the highest;
    if below all keys, the lowest."""
    if not coi_rate_table:
        return None
    entries = sorted(coi_rate_table, key=lambda e: e.get("attained_age", 0))
    eligible = [e for e in entries if e.get("attained_age", 0) <= attained_age]
    if eligible:
        return eligible[-1].get("monthly_rate_per_thousand_cents", 0)
    return entries[0].get("monthly_rate_per_thousand_cents", 0)


def monthly_coi(face_cents, cash_value_cents, dob, charge_date, coi_rate_table, uw_class):
    """monthly_coi_charge (PRD §3.5). Returns coi in cents (>= 0)."""
    net_at_risk = face_cents - cash_value_cents
    if net_at_risk <= 0:
        return 0
    age = age_years(dob, charge_date)
    rate = coi_lookup_rate(coi_rate_table, age)
    if rate is None:
        return 0
    mult = dec(CLASS_MULT[uw_class])
    coi = (dec(net_at_risk) / dec(100000)) * dec(rate) * mult / dec(100)
    return round_half_up(coi)


def accrue_loan(loan, policy, template, as_of_date, record_rows=True):
    """policy_loan_interest_accrual: chronological walk from last_accrual_date to
    as_of_date, splitting at 365-day anniversary boundaries. Non-capitalizing by
    default; capitalizing when the template flag capitalize_loan_interest is set.
    Returns list of created accrual rows."""
    from db import store
    capitalizing = bool(template.get("capitalize_loan_interest")) or bool(
        (template.get("metadata") or {}).get("capitalize_loan_interest"))
    rows = []
    cursor = loan["last_accrual_date"]
    while cursor < as_of_date:
        period_end = min(add_years_365(cursor, 1), as_of_date)
        days = (period_end - cursor).days
        principal_base = loan["outstanding_principal_cents"]
        interest = round_half_up(
            dec(principal_base) * dec(loan["annual_interest_rate_bps"]) / dec(10000)
            * dec(days) / dec(365))
        if capitalizing:
            loan["outstanding_principal_cents"] += interest
            policy["outstanding_loan_principal_cents"] += interest
        else:
            loan["accrued_interest_cents"] += interest
            policy["accrued_loan_interest_cents"] += interest
        if record_rows:
            row = domain.stamp_append_only({
                "loan_id": loan["id"],
                "accrual_period_start": cursor,
                "accrual_period_end": period_end,
                "principal_base_cents": principal_base,
                "days_accrued": days,
                "interest_accrued_cents": interest,
            })
            store.loan_accruals[row["id"]] = row
            rows.append(row)
        cursor = period_end
    loan["last_accrual_date"] = as_of_date
    if rows:
        domain.touch(loan)
        domain.touch_policy(policy)
    return rows


def _rpu_rate(age, extra_bps):
    """Age-banded net-single-premium rate plus substandard loading."""
    if age < 40:
        rate = dec("0.30")
    elif age < 50:
        rate = dec("0.40")
    elif age < 60:
        rate = dec("0.50")
    else:
        rate = dec("0.65")
    extra = dec(extra_bps) / dec(10000) * dec("0.10")
    return rate + extra


def reduced_paid_up_face(net_available_cents, dob, effective_date, extra_bps):
    """resulting_face = round_half_up(net_available / adjusted rate).
    Caller guarantees net_available > 0."""
    age = age_years(dob, effective_date)
    rate = _rpu_rate(age, extra_bps)
    return round_half_up(dec(net_available_cents) / rate)


def extended_term_months(net_available_cents, face_cents, dob, effective_date):
    """monthly cost = round_half_up(face * banded rate); months = floor(net / cost),
    capped at 60. Raises ERR_INSUFFICIENT_CASH_VALUE when net < monthly cost."""
    age = age_years(dob, effective_date)
    if age < 40:
        rate = dec("0.0010")
    elif age < 50:
        rate = dec("0.0020")
    elif age < 60:
        rate = dec("0.0040")
    else:
        rate = dec("0.0090")
    monthly_cost = round_half_up(dec(face_cents) * rate)
    if monthly_cost <= 0 or net_available_cents < monthly_cost:
        raise errors.insufficient_cash_value(
            "Net available value cannot cover one month of extended term cost")
    months = net_available_cents // monthly_cost
    return min(months, 60)


def surrender_charge(template, policy, policy_year):
    """UNIVERSAL_LIFE only: cash_value * bracket pct_bps / 10000, half-up."""
    if template["product_type"] != "UNIVERSAL_LIFE":
        return 0
    schedule = template.get("surrender_charge_schedule") or []
    if not schedule:
        return 0
    entries = sorted(schedule, key=lambda e: e.get("policy_year_min_inclusive", 0))
    eligible = [e for e in entries if e.get("policy_year_min_inclusive", 0) <= policy_year]
    if not eligible:
        pct_bps = 0
    else:
        pct_bps = eligible[-1].get("surrender_charge_pct_bps", 0)
    return round_half_up(dec(policy["cash_value_cents"]) * dec(pct_bps) / dec(10000))


def back_premium_due(policy):
    """Sum of unpaid modal premiums from lapse (paid_to_date) forward to today,
    each plus 6% p.a. reinstatement interest from its due date. Returns
    (total_cents, n_periods_owed)."""
    from db import store
    lapse_date = policy["paid_to_date"]
    request_date = store.current_date()
    months = MODE_MONTHS[policy["premium_mode"]]
    modal = policy["modal_premium_cents"]
    total = 0
    n = 0
    k = 1
    while True:
        due_date = add_months(lapse_date, k * months)
        if due_date > request_date:
            break
        days_overdue = max(0, (request_date - due_date).days)
        interest = round_half_up(
            dec(modal) * dec(REINSTATEMENT_ANNUAL_RATE) * dec(days_overdue) / dec(365))
        total += modal + interest
        n += 1
        k += 1
    return total, n


def rider_monthly_premium(rider_type, rider_face_cents, policy):
    """rider_monthly_premium_cents — deterministic carrier rule (PRD §3.10 leaves
    the schedule to the carrier)."""
    if rider_type == "GUARANTEED_INSURABILITY":
        return 0
    if rider_type == "WAIVER_OF_PREMIUM":
        months = MODE_MONTHS[policy["premium_mode"]]
        monthly_basis = policy["modal_premium_cents"] // months
        return round_half_up(dec(monthly_basis) * dec("0.05"))
    # face-carrying riders: 0.1% of rider face per month
    return round_half_up(dec(rider_face_cents) * dec("0.001"))
