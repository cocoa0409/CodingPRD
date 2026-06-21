"""Calculation rules (PRD §2.5, §2.9, §3.5, §3.7, §3.8).

All money is integer cents. The coinsurance product is floored before any clamp;
the installment base is floored per-installment with the remainder reconciled into
the final installment. Months are whole-calendar-month counts.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import db
from services import clock


# ---------------------------------------------------------------------------
# Date / month arithmetic (PRD §2.5)
# ---------------------------------------------------------------------------
def add_months(d: date, months: int) -> date:
    """Calendar-month addition; the day is clamped to the end of the target
    month when the source day does not exist there (PRD §2.5)."""
    total = (d.year * 12 + (d.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    # clamp day to last day of the target month
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    from datetime import timedelta

    last_day = (next_month_first - timedelta(days=1)).day
    day = min(d.day, last_day)
    return date(year, month, day)


def whole_months_between(start: date, end: date) -> int:
    """Number of WHOLE calendar months from start up to end (PRD §2.5).

    Counts completed months: from start, how many month-additions still land on
    or before end. Negative if end precedes start.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months >= 0:
        # if the day-of-month hasn't been reached yet, one fewer whole month
        if add_months(start, months) > end:
            months -= 1
    else:
        if add_months(start, months) < end:
            months += 1
    return months


# ---------------------------------------------------------------------------
# Coverage accumulator (PRD §2.9, §3.8)
# ---------------------------------------------------------------------------
def coinsurance_pct_for(category: str, plan: Dict[str, Any]) -> int:
    if category == "PREVENTIVE":
        return plan["preventive_coinsurance_pct"]
    if category == "BASIC":
        return plan["basic_coinsurance_pct"]
    return plan["major_coinsurance_pct"]  # MAJOR


def _benefit(fee_cents: int, category: str, plan: Dict[str, Any],
             deductible_met_cents: int, annual_benefit_used_cents: int) -> tuple[int, int]:
    """Shared deductible+coinsurance arithmetic. Returns (carrier, gross_benefit).

    carrier = min(gross_benefit, remaining_annual_max)
    """
    pct = coinsurance_pct_for(category, plan)
    remaining_deductible = max(0, plan["deductible_cents"] - deductible_met_cents)
    deductible_applied = min(remaining_deductible, fee_cents)
    after_deductible = fee_cents - deductible_applied
    gross_benefit = (after_deductible * pct) // 100  # floor
    remaining_annual_max = max(0, plan["annual_maximum_cents"] - annual_benefit_used_cents)
    carrier = min(gross_benefit, remaining_annual_max)
    return carrier, gross_benefit


def estimated_insurance_benefit(item: Dict[str, Any]) -> int:
    """Forward-looking estimate (PRD §3.8). Reads the accumulator as-of-now.

    Selects the patient's ACTIVE coverage with the latest coverage_start_date
    (tie-break earliest created_at). No active coverage -> 0.
    """
    plan_rec = db.treatment_plans[item["treatment_plan_id"]]
    patient_id = plan_rec["patient_id"]
    coverage = select_active_coverage(patient_id)
    if coverage is None:
        return 0
    plan = db.insurance_plans[coverage["insurance_plan_id"]]
    carrier, _gross = _benefit(
        item["fee_cents"], item["category"], plan,
        coverage["deductible_met_cents"], coverage["annual_benefit_used_cents"],
    )
    return carrier


def select_active_coverage(patient_id: str) -> Optional[Dict[str, Any]]:
    """Patient's ACTIVE coverage with the latest coverage_start_date; tie broken
    by the earliest created_at (PRD §3.8)."""
    candidates = [
        c for c in db.patient_coverages.values()
        if c["patient_id"] == patient_id and c["status"] == "ACTIVE"
    ]
    if not candidates:
        return None
    # Sort: latest start date first; on equal start date, earliest creation first.
    candidates.sort(key=lambda c: (c["coverage_start_date"], -c["_seq"]), reverse=True)
    return candidates[0]


def adjudicated_benefit(claim: Dict[str, Any]) -> tuple[int, int]:
    """Chronological actual (PRD §3.8). Reads the LIVE accumulator.

    Returns (carrier_paid_cents, gross_benefit). Caller derives PAID vs
    PARTIALLY_PAID by comparing carrier_paid to gross_benefit.
    """
    item = db.treatment_plan_items[claim["treatment_plan_item_id"]]
    coverage = db.patient_coverages[claim["patient_coverage_id"]]
    plan = db.insurance_plans[coverage["insurance_plan_id"]]
    carrier, gross = _benefit(
        claim["billed_fee_cents"], item["category"], plan,
        coverage["deductible_met_cents"], coverage["annual_benefit_used_cents"],
    )
    return carrier, gross


def deductible_consumed(fee_cents: int, plan: Dict[str, Any], deductible_met_cents: int) -> int:
    """How much deductible THIS claim consumes (for accumulator updates)."""
    remaining_deductible = max(0, plan["deductible_cents"] - deductible_met_cents)
    return min(remaining_deductible, fee_cents)


# ---------------------------------------------------------------------------
# Annual benefit accumulator recompute (PRD §2.9, §3.8)
# ---------------------------------------------------------------------------
def recompute_annual_max_reached(coverage: Dict[str, Any]) -> None:
    plan = db.insurance_plans[coverage["insurance_plan_id"]]
    coverage["annual_max_reached"] = (
        coverage["annual_benefit_used_cents"] >= plan["annual_maximum_cents"]
    )


# ---------------------------------------------------------------------------
# Payment plan schedule (PRD §3.7)
# ---------------------------------------------------------------------------
def payment_plan_schedule(principal_cents: int, installment_count: int) -> tuple[int, int]:
    """Returns (installment_amount_cents, final_installment_cents)."""
    base = principal_cents // installment_count  # floor
    final = principal_cents - base * (installment_count - 1)
    return base, final


# ---------------------------------------------------------------------------
# Frequency & waiting eligibility (PRD §3.5)
# ---------------------------------------------------------------------------
def waiting_ok(category: str, coverage: Dict[str, Any], plan: Dict[str, Any]) -> bool:
    if category != "MAJOR":
        return True
    start = clock.parse_date(coverage["coverage_start_date"])
    cur = clock.now().date()
    months_covered = whole_months_between(start, cur)
    return months_covered >= plan["major_waiting_period_months"]


def frequency_ok(patient_id: str, cdt_code: str, plan: Dict[str, Any]) -> bool:
    """Eligible if no prior PAID/PARTIALLY_PAID claim shares the same cdt_code,
    or the gap since the most recent such claim's adjudication date is >= the
    plan's frequency_limit_months (PRD §3.5)."""
    prior_dates: List[date] = []
    for claim in db.claims.values():
        if claim["patient_id"] != patient_id:
            continue
        if claim["adjudication_status"] not in ("PAID", "PARTIALLY_PAID"):
            continue
        item = db.treatment_plan_items.get(claim["treatment_plan_item_id"])
        if item is None or item["cdt_code"] != cdt_code:
            continue
        adj = claim.get("_adjudicated_at_date")
        if adj is not None:
            prior_dates.append(adj)
    if not prior_dates:
        return True
    most_recent = max(prior_dates)
    cur = clock.now().date()
    gap = whole_months_between(most_recent, cur)
    return gap >= plan["frequency_limit_months"]


# ---------------------------------------------------------------------------
# Recare next-due (PRD §3.7)
# ---------------------------------------------------------------------------
def recare_next_due(last_visit_date: str, interval_months: int) -> str:
    d = clock.parse_date(last_visit_date)
    return add_months(d, interval_months).isoformat()


# ---------------------------------------------------------------------------
# Patient balance (PRD §3.1, §3.7)
# ---------------------------------------------------------------------------
def recompute_patient_balance(patient_id: str) -> None:
    """balance_owed_cents = running total of patient_responsibility_cents across
    the patient's claims that are NOT yet covered by an ACTIVE payment plan
    (PRD §3.1, scaffold PatientCoverage.balance_owed_cents).

    A claim financed by an ACTIVE plan is excluded from the raw sum; once that
    plan leaves ACTIVE (DEFAULTED or PAID_OFF) the claim's responsibility re-enters
    the sum, which is how a defaulted plan's outstanding amount "returns to" the
    patient balance (PRD §3.7). VOID claims have zero responsibility and never count.
    """
    patient = db.patients.get(patient_id)
    if patient is None:
        return

    active_plan_claim_ids = {
        pp["claim_id"] for pp in db.payment_plans.values()
        if pp["patient_id"] == patient_id and pp["status"] == "ACTIVE"
    }

    total = 0
    for claim in db.claims.values():
        if claim["patient_id"] != patient_id:
            continue
        if claim["adjudication_status"] == "VOID":
            continue
        if claim["id"] in active_plan_claim_ids:
            continue
        total += claim["patient_responsibility_cents"]

    patient["balance_owed_cents"] = total
