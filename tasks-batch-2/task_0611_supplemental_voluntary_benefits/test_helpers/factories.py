"""Payload factories — one per entity, input fields only.

Only fields the client supplies are present; computed/system fields are omitted.
Field names match the PRD verbatim.
"""
from .constants import (
    PRODUCT_A_BASE_PREMIUM_CENTS,
    PRODUCT_A_ANNUAL_CAP_CENTS,
    PRODUCT_A_EOI_SURCHARGE_BPS,
    PRODUCT_A_PORTABILITY_LOADUP_BPS,
    GI_WINDOW_START,
    GI_WINDOW_END,
    BENEFIT_YEAR_START,
    VALID_ROUTING_NUMBER,
)

_email_counter = [0]


def _unique_email(prefix="member"):
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@acme.test"


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Acme Co",
        "section_125_plan_active": True,
        "pay_periods_per_year": 52,
    }
    defaults.update(overrides)
    return defaults


def create_plan_product_payload(employer_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "policy_type": "ACCIDENT",
        "product_name": "AccidentPlus",
        "weekly_premium_cents": PRODUCT_A_BASE_PREMIUM_CENTS,
        "annual_benefit_cap_cents": PRODUCT_A_ANNUAL_CAP_CENTS,
        "eoi_surcharge_bps": PRODUCT_A_EOI_SURCHARGE_BPS,
        "portability_loadup_bps": PRODUCT_A_PORTABILITY_LOADUP_BPS,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_item_payload(plan_product_id, **overrides) -> dict:
    defaults = {
        "plan_product_id": plan_product_id,
        "event_code": "FRACTURE",
        "flat_benefit_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_period_payload(employer_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "label": "OE-2026",
        "gi_window_start": GI_WINDOW_START,
        "gi_window_end": GI_WINDOW_END,
        "benefit_year_start": BENEFIT_YEAR_START,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(employer_id, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "full_name": "Test Member",
        "email": _unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_account_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "routing_number": VALID_ROUTING_NUMBER,
        "account_last4": "4321",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(
    employee_id, plan_product_id, enrollment_period_id, **overrides
) -> dict:
    defaults = {
        "employee_id": employee_id,
        "plan_product_id": plan_product_id,
        "enrollment_period_id": enrollment_period_id,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_deduction_payload(pay_period_index, outcome, **overrides) -> dict:
    defaults = {
        "pay_period_index": pay_period_index,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(
    enrollment_id, disbursement_account_id, event_code, event_date, **overrides
) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "disbursement_account_id": disbursement_account_id,
        "event_code": event_code,
        "event_date": event_date,
    }
    defaults.update(overrides)
    return defaults


def create_portability_conversion_payload(expected_enrollment_version, **overrides) -> dict:
    defaults = {
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def deny_claim_payload(denial_reason="Not covered", **overrides) -> dict:
    defaults = {"denial_reason": denial_reason}
    defaults.update(overrides)
    return defaults
