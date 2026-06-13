"""Payload factories — one per entity, input fields only (PRD §3 / §4)."""
from .constants import (
    EMPLOYER_DEFAULTS,
    STANDARD_POLICY,
    FEE_SCHEDULE,
    PERIOD_START,
    PERIOD_END,
    WORKER_HIRE_DATE,
    WORKER_HOURLY_RATE_CENTS,
)


def create_employer_payload(**overrides) -> dict:
    """Employer create body. Required: legal_name, state_code, pay_frequency.
    Optional knobs default per PRD §3.1; included explicitly so fixtures are deterministic."""
    payload = {
        "legal_name": "Acme",
        "state_code": "CA",
        "pay_frequency": "WEEKLY",
        "funding_balance_cents": EMPLOYER_DEFAULTS["funding_balance_cents"],
        "max_advance_pct_of_available": EMPLOYER_DEFAULTS["max_advance_pct_of_available"],
        "per_period_advance_cap_count": EMPLOYER_DEFAULTS["per_period_advance_cap_count"],
        "cooling_off_hours": EMPLOYER_DEFAULTS["cooling_off_hours"],
    }
    payload.update(overrides)
    return payload


def create_advance_policy_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "tier": STANDARD_POLICY["tier"],
        "min_tenure_days": STANDARD_POLICY["min_tenure_days"],
        "per_advance_floor_cents": STANDARD_POLICY["per_advance_floor_cents"],
        "per_advance_ceiling_cents": STANDARD_POLICY["per_advance_ceiling_cents"],
        "cumulative_period_ceiling_cents": STANDARD_POLICY["cumulative_period_ceiling_cents"],
    }
    payload.update(overrides)
    return payload


def create_fee_schedule_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "expedite_flat_fee_cents": FEE_SCHEDULE["expedite_flat_fee_cents"],
        "expedite_pct_fee": FEE_SCHEDULE["expedite_pct_fee"],
        "max_total_fee_cents": FEE_SCHEDULE["max_total_fee_cents"],
        "tip_allowed": FEE_SCHEDULE["tip_allowed"],
    }
    payload.update(overrides)
    return payload


def create_pay_period_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "start_at": PERIOD_START,
        "end_at": PERIOD_END,
    }
    payload.update(overrides)
    return payload


def create_worker_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "external_payroll_ref": "EMP-1",
        "full_name": "Wanda",
        "hourly_rate_cents": WORKER_HOURLY_RATE_CENTS,
        "hire_date": WORKER_HIRE_DATE,
    }
    payload.update(overrides)
    return payload


def create_time_entry_payload(pay_period_id, worker_id, shift_start_at, shift_end_at,
                              hours_worked, **overrides) -> dict:
    payload = {
        "pay_period_id": pay_period_id,
        "worker_id": worker_id,
        "shift_start_at": shift_start_at,
        "shift_end_at": shift_end_at,
        "hours_worked": hours_worked,
    }
    payload.update(overrides)
    return payload


def create_advance_payload(worker_id, pay_period_id, requested_principal_cents,
                           expected_worker_version, **overrides) -> dict:
    payload = {
        "worker_id": worker_id,
        "pay_period_id": pay_period_id,
        "requested_principal_cents": requested_principal_cents,
        "disbursement_speed": "STANDARD",
        "tip_cents": 0,
        "expected_worker_version": expected_worker_version,
    }
    payload.update(overrides)
    return payload


def create_repayment_batch_payload(pay_period_id, **overrides) -> dict:
    payload = {"pay_period_id": pay_period_id}
    payload.update(overrides)
    return payload


def create_reconciliation_statement_payload(pay_period_id, **overrides) -> dict:
    payload = {"pay_period_id": pay_period_id}
    payload.update(overrides)
    return payload
