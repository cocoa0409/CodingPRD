"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_PLAN_YEAR_CAPS,
    DEFAULT_COVERAGE_START,
    DEFAULT_COVERAGE_END,
    DEFAULT_RUN_OUT_END,
)


def create_participant_payload(**overrides) -> dict:
    """POST /participants input. email, full_name, birth_date required;
    marital_status, hdhp_covered optional (server defaults SINGLE / false)."""
    defaults = {
        "email": "participant@example.com",
        "full_name": "Test Participant",
        "birth_date": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_plan_year_payload(**overrides) -> dict:
    """POST /plan-years input. Carries the full statutory cap schedule.
    fsa_relief_mode, grace_period_end, carryover_cap_cents are optional."""
    defaults = {
        "label": "PY2026",
        "coverage_start": DEFAULT_COVERAGE_START,
        "coverage_end": DEFAULT_COVERAGE_END,
        "run_out_end": DEFAULT_RUN_OUT_END,
    }
    defaults.update(DEFAULT_PLAN_YEAR_CAPS)
    defaults.update(overrides)
    return defaults


def create_account_payload(participant_id, plan_year_id, account_type, **overrides) -> dict:
    """POST /accounts input. participant_id, plan_year_id, account_type, elected_amount_cents
    required; coverage_tier, auto_adjudication_threshold_cents optional."""
    defaults = {
        "participant_id": participant_id,
        "plan_year_id": plan_year_id,
        "account_type": account_type,
        "elected_amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(amount_cents, expected_account_version, **overrides) -> dict:
    """POST /accounts/{id}/contributions input. amount_cents, source, posted_at,
    expected_account_version required."""
    defaults = {
        "amount_cents": amount_cents,
        "source": "PAYROLL",
        "posted_at": "2026-02-01T00:00:00Z",
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(account_id, **overrides) -> dict:
    """POST /claims input. account_id, service_date, expense_category, claimed_amount_cents
    required; substantiated optional (server default false)."""
    defaults = {
        "account_id": account_id,
        "service_date": "2026-04-01",
        "expense_category": "MEDICAL",
        "claimed_amount_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(participant_id, claim_ids, **overrides) -> dict:
    """POST /reimbursement-batches input. participant_id, claim_ids required."""
    defaults = {
        "participant_id": participant_id,
        "claim_ids": claim_ids,
    }
    defaults.update(overrides)
    return defaults
