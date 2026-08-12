"""Payload factories — one per creatable entity, input fields only.

Computed/system-owned fields are never included in a factory payload; tests
that need to probe "computed input is ignored" add the field explicitly.
"""

DEFAULTS = {
    "ROLE_CODE": "SWE",
    "SKILL_CODE": "JAVA",
    "GEO_CODE": "US-CA",
    "CURRENCY": "USD",
    "PAY_RATE_FLOOR_CENTS": 5000,
    "BILL_RATE_CEILING_CENTS": 12000,
    "MAX_MARKUP_PCT": 0.25,
    "EFFECTIVE_FROM": "2026-01-01",
    "EFFECTIVE_TO": "2027-01-01",
    "SUPPLIER_NAME": "Test Supplier",
    "SUPPLIER_CODE": "SUP-TEST",
    "SUPPLIER_TIER": "PREFERRED",
    "ENGAGEMENT_TITLE": "Test Engagement",
    "ENGAGEMENT_TYPE": "REQUISITION",
    "PAYMENT_BASIS": "HOURLY",
    "SUPERVISION_LEVEL": "DAILY",
    "DURATION_MONTHS": 6,
    "BUDGET_CENTS": 1_000_000,
    "WORKER_FULL_NAME": "Test Worker",
    "WORKER_EMAIL": "worker@example.com",
    "BILL_RATE_CENTS": 9500,
    "PAY_RATE_CENTS": 8000,
    "START_DATE": "2026-05-01",
    "END_DATE": "2026-08-31",
    "PERIOD_START": "2026-05-04",
    "PERIOD_END": "2026-05-10",
    "SUBMITTED_HOURS": 8.0,
    "MILESTONE_NAME": "Milestone 1",
    "MILESTONE_AMOUNT_CENTS": 1_000_000,
    "MILESTONE_DUE_DATE": "2026-06-30",
}


def create_rate_card_payload(**overrides) -> dict:
    payload = {
        "role_code": DEFAULTS["ROLE_CODE"],
        "skill_code": DEFAULTS["SKILL_CODE"],
        "geo_code": DEFAULTS["GEO_CODE"],
        "currency": DEFAULTS["CURRENCY"],
        "pay_rate_floor_cents": DEFAULTS["PAY_RATE_FLOOR_CENTS"],
        "bill_rate_ceiling_cents": DEFAULTS["BILL_RATE_CEILING_CENTS"],
        "max_markup_pct": DEFAULTS["MAX_MARKUP_PCT"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SUPPLIER_NAME"],
        "supplier_code": DEFAULTS["SUPPLIER_CODE"],
        "tier": DEFAULTS["SUPPLIER_TIER"],
    }
    payload.update(overrides)
    return payload


def create_engagement_payload(**overrides) -> dict:
    payload = {
        "title": DEFAULTS["ENGAGEMENT_TITLE"],
        "engagement_type": DEFAULTS["ENGAGEMENT_TYPE"],
        "role_code": DEFAULTS["ROLE_CODE"],
        "skill_code": DEFAULTS["SKILL_CODE"],
        "geo_code": DEFAULTS["GEO_CODE"],
        "payment_basis": DEFAULTS["PAYMENT_BASIS"],
        "supervision_level": DEFAULTS["SUPERVISION_LEVEL"],
        "duration_months": DEFAULTS["DURATION_MONTHS"],
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_worker_payload(supplier_id: str, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "full_name": DEFAULTS["WORKER_FULL_NAME"],
        "email": DEFAULTS["WORKER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(
    worker_id: str,
    engagement_id: str,
    offer_id: str,
    rate_card_id: str,
    **overrides,
) -> dict:
    payload = {
        "worker_id": worker_id,
        "engagement_id": engagement_id,
        "offer_id": offer_id,
        "rate_card_id": rate_card_id,
        "bill_rate_cents": DEFAULTS["BILL_RATE_CENTS"],
        "pay_rate_cents": DEFAULTS["PAY_RATE_CENTS"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_timesheet_payload(assignment_id: str, **overrides) -> dict:
    payload = {
        "assignment_id": assignment_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "submitted_hours": DEFAULTS["SUBMITTED_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_milestone_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MILESTONE_NAME"],
        "amount_cents": DEFAULTS["MILESTONE_AMOUNT_CENTS"],
        "due_date": DEFAULTS["MILESTONE_DUE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(supplier_id: str, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
    }
    payload.update(overrides)
    return payload


def create_conversion_request_payload(worker_id: str, assignment_id: str, **overrides) -> dict:
    payload = {
        "worker_id": worker_id,
        "assignment_id": assignment_id,
    }
    payload.update(overrides)
    return payload
