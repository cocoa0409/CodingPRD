"""Payload factories — one per entity, input fields only."""
from datetime import date, timedelta
from typing import List, Optional

DEFAULTS = {
    "STATE_CODE": "AA",
    "LEGAL_NAME": "Test Household",
    "FEIN": "123456789",
    "PAY_FREQUENCY": "WEEKLY",
    "MIN_WAGE_CENTS": 1000,
    "HOURLY_RATE_CENTS": 3000,
    "HIRE_DATE": "2026-01-05",
    "AGREEMENT_EFFECTIVE_FROM": "2026-01-01",
    "NEW_HIRE_REPORT_DATE": "2026-01-06",
    "WORKER_FULL_NAME": "Test Worker",
    "SSN": "123456789",
}


def create_state_rule_pack_payload(state_code: str = "AA", **overrides) -> dict:
    defaults = {
        "state_code": state_code,
        "min_pay_frequency": "WEEKLY",
        "weekly_ot_threshold_minutes": 2400,
        "daily_ot_threshold_minutes": 0,
        "daily_dt_threshold_minutes": 0,
        "live_in_weekly_ot_eligible": False,
        "live_in_daily_ot_eligible": False,
        "min_wage_cents": DEFAULTS["MIN_WAGE_CENTS"],
        "sit_rate": 0.05,
        "suta_rate": 0.02,
        "suta_wage_base_cents": 10000000,
        "workers_comp_required": False,
        "new_hire_report_days": 20,
        "pay_stub_required": True,
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "primary_state_code": DEFAULTS["STATE_CODE"],
        "fein": DEFAULTS["FEIN"],
        "pay_frequency": DEFAULTS["PAY_FREQUENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["WORKER_FULL_NAME"],
        "work_state_code": DEFAULTS["STATE_CODE"],
        "hire_date": DEFAULTS["HIRE_DATE"],
        "work_arrangement": "LIVE_OUT",
    }
    defaults.update(overrides)
    return defaults


def classification_answers_employee() -> List[dict]:
    """Score 0 -> EMPLOYEE."""
    return [
        {"question_key": "controls_schedule", "answer": "EMPLOYER"},
        {"question_key": "supplies_own_tools", "answer": "EMPLOYER"},
        {"question_key": "hires_own_substitutes", "answer": "NOT_ALLOWED"},
        {"question_key": "paid_by", "answer": "HOURLY"},
    ]


def classification_answers_contractor() -> List[dict]:
    """Score 4 -> CONTRACTOR."""
    return [
        {"question_key": "controls_schedule", "answer": "WORKER"},
        {"question_key": "supplies_own_tools", "answer": "WORKER"},
        {"question_key": "hires_own_substitutes", "answer": "ALLOWED"},
        {"question_key": "paid_by", "answer": "PROJECT_NOT_HOURS"},
    ]


def create_agreement_payload(expected_worker_version: int, **overrides) -> dict:
    defaults = {
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "pay_method": "HOURLY",
        "effective_from": DEFAULTS["AGREEMENT_EFFECTIVE_FROM"],
        "expected_worker_version": expected_worker_version,
    }
    defaults.update(overrides)
    return defaults


def make_work_entries(start_date: str, minutes_per_day: List[int]) -> List[dict]:
    """Per-day entries on consecutive calendar days starting at start_date."""
    first = date.fromisoformat(start_date)
    return [
        {
            "work_date": (first + timedelta(days=i)).isoformat(),
            "worked_minutes": minutes,
        }
        for i, minutes in enumerate(minutes_per_day)
    ]


def create_timesheet_payload(period_start: str, period_end: str, entries: List[dict]) -> dict:
    return {"period_start": period_start, "period_end": period_end, "entries": entries}


def create_pay_run_payload(period_start: str, period_end: str, pay_date: str) -> dict:
    return {"period_start": period_start, "period_end": period_end, "pay_date": pay_date}


def create_leave_request_payload(start_date: str, end_date: str, requested_minutes: int) -> dict:
    return {"start_date": start_date, "end_date": end_date, "requested_minutes": requested_minutes}


def create_deposit_payload(tax_year: int, quarter: int, amount_cents: int, remitted_on: str) -> dict:
    return {
        "tax_year": tax_year,
        "quarter": quarter,
        "amount_cents": amount_cents,
        "remitted_on": remitted_on,
    }


def create_quarterly_filing_payload(tax_year: int, quarter: int) -> dict:
    return {"tax_year": tax_year, "quarter": quarter}


def create_workers_comp_policy_payload(state_code: str, coverage_start: str, coverage_end: str,
                                       policy_number: str = "WC-1") -> dict:
    return {
        "state_code": state_code,
        "policy_number": policy_number,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }


def create_year_end_package_payload(tax_year: int) -> dict:
    return {"tax_year": tax_year}
