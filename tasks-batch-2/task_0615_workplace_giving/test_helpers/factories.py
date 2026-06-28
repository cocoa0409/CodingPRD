"""Payload factories — one per entity, input fields only.

Only fields with source: input are accepted by the create endpoints; system/computed
fields are omitted (the server sets them).
"""
from .constants import (
    DEFAULT_TAX_YEAR,
    YEAR_WINDOW_START,
    YEAR_WINDOW_END,
    DEFAULT_SALARY_CENTS,
)


def create_program_payload(**overrides) -> dict:
    """Program create payload. Only name + tax_year are required; the rest take server defaults."""
    defaults = {
        "name": "Test Program",
        "tax_year": DEFAULT_TAX_YEAR,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "email": "employee@co.com",
        "full_name": "Test Employee",
        "annual_salary_cents": DEFAULT_SALARY_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_charity_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "legal_name": "Test Charity",
        "ein": "12-3456789",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(program_id: str, charity_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "charity_id": charity_id,
        "name": "Test Campaign",
        "goal_cents": 1000000,
        "window_start": YEAR_WINDOW_START,
        "window_end": YEAR_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(program_id: str, employee_id: str, campaign_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "employee_id": employee_id,
        "campaign_id": campaign_id,
        "donation_type": "ONE_TIME",
        "funding_method": "CREDIT",
        "base_amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_schedule_payload(program_id: str, employee_id: str, campaign_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "employee_id": employee_id,
        "campaign_id": campaign_id,
        "per_period_amount_cents": 1000,
        "window_start": YEAR_WINDOW_START,
        "window_end": YEAR_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_log_payload(program_id: str, employee_id: str, charity_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "employee_id": employee_id,
        "charity_id": charity_id,
        "minutes": 120,
        "activity_date": "2026-03-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_batch_payload(program_id: str, charity_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "charity_id": charity_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def stage_grant_payload(source_type: str, source_id: str, expected_batch_version: int, **overrides) -> dict:
    defaults = {
        "source_type": source_type,
        "source_id": source_id,
        "expected_batch_version": expected_batch_version,
    }
    defaults.update(overrides)
    return defaults
