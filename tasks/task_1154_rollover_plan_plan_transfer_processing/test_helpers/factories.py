"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import P1_DOB, P1_SEPARATION_DATE


def create_plan_payload(**overrides) -> dict:
    defaults = {"plan_name": "Plan A", "plan_type": "PLAN_401K"}
    defaults.update(overrides)
    return defaults


def create_freeze_window_payload(**overrides) -> dict:
    defaults = {
        "start_date": "2026-06-10",
        "end_date": "2026-06-20",
        "reason": "recordkeeper conversion blackout",
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat One",
        "date_of_birth": P1_DOB,
        "employment_status": "SEPARATED",
        "marital_status": "SINGLE",
        "separation_date": P1_SEPARATION_DATE,
    }
    defaults.update(overrides)
    # Drop keys explicitly set to None (e.g., separation_date for ACTIVE participants).
    return {k: v for k, v in defaults.items() if v is not None}


def create_account_payload(participant_id, plan_id, **overrides) -> dict:
    defaults = {"participant_id": participant_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def money_source_row(source_type, balance_cents, basis_cents=0, vested_pct=100) -> dict:
    return {
        "source_type": source_type,
        "balance_cents": balance_cents,
        "basis_cents": basis_cents,
        "vested_pct": vested_pct,
    }


def create_loan_payload(**overrides) -> dict:
    defaults = {
        "outstanding_balance_cents": 250000,
        "interest_rate_bp": 500,
        "term_months": 60,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(case_type, **overrides) -> dict:
    defaults = {"case_type": case_type}
    defaults.update(overrides)
    return defaults


def create_verification_payload(direction, method="PLAN_LETTER", **overrides) -> dict:
    defaults = {"direction": direction, "method": method}
    defaults.update(overrides)
    return defaults


def create_redeposit_payload(receiving_account_id, amount_cents, received_date, **overrides) -> dict:
    defaults = {
        "receiving_account_id": receiving_account_id,
        "amount_cents": amount_cents,
        "received_date": received_date,
    }
    defaults.update(overrides)
    return defaults


def post_credit_payload(**overrides) -> dict:
    defaults = {
        "pre_tax_cents": 0,
        "roth_cents": 0,
        "roth_basis_cents": 0,
        "after_tax_basis_cents": 0,
    }
    defaults.update(overrides)
    return defaults
