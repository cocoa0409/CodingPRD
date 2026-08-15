"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_PLAN_END,
    DEFAULT_PLAN_START,
    DEFAULT_QUOTA_CENTS,
    DEFAULT_TRANSACTION_DATE,
    FLAT_CURVE_TIERS,
)


def create_program_payload(**overrides) -> dict:
    defaults = {"name": "Test Program"}
    defaults.update(overrides)
    return defaults


def create_plan_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Test Plan",
        "effective_start_date": DEFAULT_PLAN_START,
        "effective_end_date": DEFAULT_PLAN_END,
        "curve_tiers": [dict(t) for t in FLAT_CURVE_TIERS],
    }
    defaults.update(overrides)
    return defaults


def revise_plan_payload(expected_plan_version, **overrides) -> dict:
    payload = {"expected_plan_version": expected_plan_version}
    payload.update(overrides)
    return payload


def create_rep_payload(program_id, name, employee_ref, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": name,
        "employee_ref": employee_ref,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(program_id, rep_id, plan_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "rep_id": rep_id,
        "plan_id": plan_id,
        "quota_cents": DEFAULT_QUOTA_CENTS,
        "effective_start_date": DEFAULT_PLAN_START,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(program_id, external_ref, amount_cents, splits,
                               **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "external_ref": external_ref,
        "amount_cents": amount_cents,
        "transaction_date": DEFAULT_TRANSACTION_DATE,
        "splits": splits,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(assignment_id, amount_cents, reason,
                              **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "amount_cents": amount_cents,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(assignment_id, period_index, reason,
                           requested_amount_cents, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "period_index": period_index,
        "reason": reason,
        "requested_amount_cents": requested_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_export_payload(program_id, period_index,
                                  **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period_index": period_index,
    }
    defaults.update(overrides)
    return defaults


def close_period_payload(expected_program_version) -> dict:
    return {"expected_program_version": expected_program_version}
