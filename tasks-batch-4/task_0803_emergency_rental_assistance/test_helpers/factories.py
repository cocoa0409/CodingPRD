"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_INCOME_LIMIT_BY_SIZE,
    DEFAULT_MONTHS_CAP,
    TEST_DEFAULTS,
)


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": "ERAP-Test",
        "funding_pool_total_cents": TEST_DEFAULTS["FUNDING_POOL_TOTAL_CENTS"],
        "per_month_max_cents": TEST_DEFAULTS["PER_MONTH_MAX_CENTS"],
        "monthly_income_limit_by_size": dict(DEFAULT_INCOME_LIMIT_BY_SIZE),
        "months_cap": DEFAULT_MONTHS_CAP,
    }
    payload.update(overrides)
    return payload


def create_tenant_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Household",
        "email": "tenant@example.com",
        "household_size": 2,
    }
    payload.update(overrides)
    return payload


def create_landlord_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Test Landlord LLC",
        "email": "landlord@example.com",
    }
    payload.update(overrides)
    return payload


def submit_w9_payload(**overrides) -> dict:
    payload = {
        "tin": "12-3456789",
        "banking_last4": "0000",
        "mailing_address": "1 Test St",
    }
    payload.update(overrides)
    return payload


def create_unit_payload(landlord_id, **overrides) -> dict:
    payload = {
        "landlord_id": landlord_id,
        "address": "1 Test St",
        "monthly_rent_cents": TEST_DEFAULTS["UNIT_RENT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(program_id, tenant_id, landlord_id, unit_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "tenant_id": tenant_id,
        "landlord_id": landlord_id,
        "unit_id": unit_id,
        "monthly_rent_cents": TEST_DEFAULTS["APP_RENT_CENTS"],
        "requested_prospective_months": 3,
        "arrears_start_month": "2025-12",
        "arrears_end_month": "2026-01",
        "prospective_start_date": "2026-03-01",
        "prospective_end_date": "2026-05-31",
    }
    payload.update(overrides)
    return payload


def income_source_payload(source_type="WAGES", monthly_amount_cents=400_000, **overrides) -> dict:
    payload = {
        "source_type": source_type,
        "monthly_amount_cents": monthly_amount_cents,
    }
    payload.update(overrides)
    return payload


def ledger_payload(lines=None, **overrides) -> dict:
    payload = {"lines": list(lines) if lines is not None else []}
    payload.update(overrides)
    return payload


def ledger_line(month, line_type, charge_cents=0, payment_cents=0) -> dict:
    line = {"month": month, "line_type": line_type}
    if line_type == "CHARGE":
        line["charge_cents"] = charge_cents
    else:
        line["payment_cents"] = payment_cents
    return line


def disbursement_payload(amount_cents, months_covered, coverage_kind,
                         expected_application_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "months_covered": months_covered,
        "coverage_kind": coverage_kind,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def recertification_payload(requested_additional_months, **overrides) -> dict:
    payload = {"requested_additional_months": requested_additional_months}
    payload.update(overrides)
    return payload


def recapture_case_payload(application_id, disbursement_id, reason, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "disbursement_id": disbursement_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload
