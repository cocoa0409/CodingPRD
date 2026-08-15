"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import (
    CLOCK_START,
    DEFAULT_CAPS,
    PAY_DATE,
    PERIOD_END,
    PERIOD_START,
)

_fein_counter = itertools.count(1)
_case_counter = itertools.count(1)


def _next_fein() -> str:
    n = next(_fein_counter)
    return f"{10 + (n % 80):02d}-{1000000 + n:07d}"


def _next_case(prefix: str = "CS-") -> str:
    return f"{prefix}{next(_case_counter)}"


def clock_payload(to_iso8601: str = CLOCK_START) -> dict:
    return {"to_iso8601": to_iso8601}


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer",
        "fein": _next_fein(),
        "remittance_timing": "SAME_DAY",
        "payroll_calendar": {
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "pay_date": PAY_DATE,
        },
        "administrative_fee_policy": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_state_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "caps": dict(DEFAULT_CAPS),
        "min_wage_multiplier": 0.75,
        "hourly_floor_cents": 0,
        "fee_deductible_from_wages": True,
    }
    defaults.update(overrides)
    if "caps" in overrides:
        defaults["caps"] = overrides["caps"]
    return defaults


def create_authority_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Authority",
        "authority_type": "CHILD_SUPPORT_AGENCY",
        "state_code": "CA",
        "accepted_case_number_pattern": "^CS-",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(employer_id, expected_employer_version, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "full_name": "Test Worker",
        "work_state_code": "CA",
        "pay_frequency": "SEMIMONTHLY",
        "hourly_rate_cents": 0,
        "expected_employer_version": expected_employer_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(issuing_authority_id, expected_employee_version, **overrides) -> dict:
    defaults = {
        "issuing_authority_id": issuing_authority_id,
        "case_number": _next_case(),
        "order_type": "CHILD_SUPPORT",
        "amount_model": "FIXED_AMOUNT_PER_PERIOD",
        "amount_value": 10000,
        "total_balance_cents": 999999,
        "effective_date": PERIOD_START,
        "expected_employee_version": expected_employee_version,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_run_payload(employer_id, expected_employer_version, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "pay_date": PAY_DATE,
        "expected_employer_version": expected_employer_version,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "gross_earnings_cents": 100000,
        "mandatory_deductions_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(employer_id, authority_id, payroll_run_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "authority_id": authority_id,
        "payroll_run_id": payroll_run_id,
    }
    defaults.update(overrides)
    return defaults


def pay_run_payload(expected_employer_version) -> dict:
    return {"expected_employer_version": expected_employer_version}


def suspend_payload(hold_reason: str = "DISPUTED") -> dict:
    return {"hold_reason": hold_reason}


def answer_payload(answer_type: str = "ACCEPTED", answer_date: str = PAY_DATE) -> dict:
    return {"answer_type": answer_type, "answer_date": answer_date}


def refund_payload(refund_amount_cents, payroll_run_id, reason: str = "OVERWITHHELD") -> dict:
    return {
        "refund_amount_cents": refund_amount_cents,
        "reason": reason,
        "payroll_run_id": payroll_run_id,
    }


def terminate_employee_payload(termination_date: str = "2026-08-10") -> dict:
    return {"termination_date": termination_date}


def terminate_order_payload(termination_reason: str = "EMPLOYEE_SEPARATION") -> dict:
    return {"termination_reason": termination_reason}


def reject_order_payload(reason: str = "bad paperwork") -> dict:
    return {"reason": reason}
