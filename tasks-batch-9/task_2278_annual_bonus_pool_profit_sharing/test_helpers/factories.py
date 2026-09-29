"""Payload factories: one per write endpoint, carrying only input fields."""

import itertools

from .constants import (
    PAYMENT_DATE,
    PLAN_PERIOD_END,
    PLAN_PERIOD_START,
    TEST_DEFAULTS,
)

_unit_code_counter = itertools.count(1)
_plan_name_counter = itertools.count(1)
_employee_code_counter = itertools.count(1)


def unique_unit_code(prefix: str = "BU") -> str:
    return f"{prefix}{next(_unit_code_counter):04d}"


def unique_plan_name(prefix: str = "FY26 Plan") -> str:
    return f"{prefix} {next(_plan_name_counter):04d}"


def unique_employee_code(prefix: str = "E") -> str:
    return f"{prefix}{next(_employee_code_counter):05d}"


# ─── Bonus plan ───────────────────────────────────────────────────────────
def bonus_plan_payload(**overrides) -> dict:
    payload = {
        "plan_year": 2026,
        "plan_name": unique_plan_name(),
        "plan_period_start": PLAN_PERIOD_START,
        "plan_period_end": PLAN_PERIOD_END,
        "payment_date": PAYMENT_DATE,
        "company_weight_pct": TEST_DEFAULTS["COMPANY_WEIGHT_PCT"],
        "business_unit_weight_pct": TEST_DEFAULTS["BUSINESS_UNIT_WEIGHT_PCT"],
        "individual_weight_pct": TEST_DEFAULTS["INDIVIDUAL_WEIGHT_PCT"],
    }
    payload.update(overrides)
    return payload


# ─── Business unit ────────────────────────────────────────────────────────
def business_unit_payload(**overrides) -> dict:
    code = overrides.pop("unit_code", None) or unique_unit_code()
    payload = {"unit_code": code, "name": f"Unit {code}"}
    payload.update(overrides)
    return payload


# ─── Job-level target ─────────────────────────────────────────────────────
def job_level_target_payload(plan_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "job_level": "L5",
        "target_bonus_pct": TEST_DEFAULTS["L5_TARGET_BONUS_PCT"],
        "guideline_min_ratio": TEST_DEFAULTS["GUIDELINE_MIN_RATIO"],
        "guideline_max_ratio": TEST_DEFAULTS["GUIDELINE_MAX_RATIO"],
    }
    payload.update(overrides)
    return payload


# ─── Company metric ───────────────────────────────────────────────────────
def company_metric_payload(plan_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "metric_code": "REVENUE",
        "weight_pct": 100.00,
        "threshold_value": TEST_DEFAULTS["METRIC_THRESHOLD_VALUE"],
        "target_value": TEST_DEFAULTS["METRIC_TARGET_VALUE"],
        "max_value": TEST_DEFAULTS["METRIC_MAX_VALUE"],
    }
    payload.update(overrides)
    return payload


def metric_actual_payload(actual_value, **overrides) -> dict:
    payload = {"actual_value": actual_value, "source_note": "audited revenue"}
    payload.update(overrides)
    return payload


# ─── Business-unit pool ───────────────────────────────────────────────────
def bu_pool_payload(plan_id: str, business_unit_id: str, **overrides) -> dict:
    payload = {"plan_id": plan_id, "business_unit_id": business_unit_id}
    payload.update(overrides)
    return payload


def submit_scorecard_payload(bu_metric_achievement_pct, **overrides) -> dict:
    payload = {
        "bu_metric_achievement_pct": bu_metric_achievement_pct,
        "scorecard_narrative": "unit result filed",
    }
    payload.update(overrides)
    return payload


def decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Participant ──────────────────────────────────────────────────────────
def participant_payload(plan_id: str, business_unit_id: str, **overrides) -> dict:
    code = overrides.pop("employee_code", None) or unique_employee_code()
    payload = {
        "plan_id": plan_id,
        "business_unit_id": business_unit_id,
        "employee_code": code,
        "full_name": f"Participant {code}",
        "job_level": "L5",
        "base_salary_cents": TEST_DEFAULTS["L5_BASE_SALARY_CENTS"],
        "hire_date": TEST_DEFAULTS["FULL_YEAR_HIRE_DATE"],
    }
    payload.update(overrides)
    return payload


# ─── Eligibility events ───────────────────────────────────────────────────
def transfer_event_payload(
    participant_id: str,
    effective_date: str,
    new_job_level: str,
    new_base_salary_cents: int,
    new_business_unit_id: str,
    **overrides,
) -> dict:
    payload = {
        "participant_id": participant_id,
        "event_type": "TRANSFER",
        "effective_date": effective_date,
        "new_job_level": new_job_level,
        "new_base_salary_cents": new_base_salary_cents,
        "new_business_unit_id": new_business_unit_id,
    }
    payload.update(overrides)
    return payload


def leave_event_payload(
    participant_id: str,
    effective_date: str,
    leave_end_date: str,
    paid_leave: bool = False,
    **overrides,
) -> dict:
    payload = {
        "participant_id": participant_id,
        "event_type": "LEAVE",
        "effective_date": effective_date,
        "leave_end_date": leave_end_date,
        "paid_leave": paid_leave,
    }
    payload.update(overrides)
    return payload


def termination_event_payload(
    participant_id: str,
    effective_date: str,
    termination_reason: str,
    **overrides,
) -> dict:
    payload = {
        "participant_id": participant_id,
        "event_type": "TERMINATION",
        "effective_date": effective_date,
        "termination_reason": termination_reason,
    }
    payload.update(overrides)
    return payload


# ─── Allocation ───────────────────────────────────────────────────────────
def propose_allocation_payload(
    proposed_allocation_cents: int, expected_pool_version: int, **overrides
) -> dict:
    payload = {
        "proposed_allocation_cents": proposed_allocation_cents,
        "allocation_rationale": "manager allocation",
        "expected_pool_version": expected_pool_version,
    }
    payload.update(overrides)
    return payload


def retract_allocation_payload(expected_pool_version: int, **overrides) -> dict:
    payload = {
        "expected_pool_version": expected_pool_version,
        "retraction_reason": "released back to the pool",
    }
    payload.update(overrides)
    return payload


# ─── Discretionary adjustment ─────────────────────────────────────────────
def discretionary_adjustment_payload(
    plan_id: str,
    award_id: str,
    adjustment_cents: int,
    expected_plan_version: int,
    **overrides,
) -> dict:
    payload = {
        "plan_id": plan_id,
        "award_id": award_id,
        "adjustment_cents": adjustment_cents,
        "justification": "retention case",
        "expected_plan_version": expected_plan_version,
    }
    payload.update(overrides)
    return payload


def adjustment_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision, "decision_note": "committee verdict recorded"}
    payload.update(overrides)
    return payload


def adjustment_reverse_payload(**overrides) -> dict:
    payload = {"decision_note": "committee reverses the approved adjustment"}
    payload.update(overrides)
    return payload


# ─── Accrual periods ──────────────────────────────────────────────────────
def accrual_period_payload(
    plan_id: str,
    period_start: str,
    period_end: str,
    forecast_company_achievement_pct,
    **overrides,
) -> dict:
    payload = {
        "plan_id": plan_id,
        "period_start": period_start,
        "period_end": period_end,
        "forecast_company_achievement_pct": forecast_company_achievement_pct,
    }
    payload.update(overrides)
    return payload


def accrual_post_payload(**overrides) -> dict:
    payload = {"posting_note": "month-end accrual posted"}
    payload.update(overrides)
    return payload


def accrual_reverse_payload(**overrides) -> dict:
    payload = {"reversal_reason": "forecast restated"}
    payload.update(overrides)
    return payload


# ─── Payout run ───────────────────────────────────────────────────────────
def payout_run_payload(plan_id: str, **overrides) -> dict:
    payload = {"plan_id": plan_id, "run_note": "annual payout"}
    payload.update(overrides)
    return payload


def settle_payload(**overrides) -> dict:
    payload = {"settlement_note": "year closed"}
    payload.update(overrides)
    return payload


# ─── Disputes ─────────────────────────────────────────────────────────────
def dispute_payload(
    plan_id: str, award_id: str, participant_id: str, **overrides
) -> dict:
    payload = {
        "plan_id": plan_id,
        "award_id": award_id,
        "participant_id": participant_id,
        "dispute_reason": "the allocation understates my contribution",
    }
    payload.update(overrides)
    return payload


def dispute_review_payload(**overrides) -> dict:
    payload = {"reviewer_note": "taken under review"}
    payload.update(overrides)
    return payload


def dispute_resolution_payload(resolution: str, **overrides) -> dict:
    payload = {"resolution": resolution, "resolution_note": "reviewed and decided"}
    payload.update(overrides)
    return payload


# ─── Logical clock ────────────────────────────────────────────────────────
def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
