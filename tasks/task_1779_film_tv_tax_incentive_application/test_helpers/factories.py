"""Payload factories — one per resource, input fields only."""
import itertools

from .constants import (
    GA_PROGRAM_DEFAULTS,
    STANDARD_START_DATE,
    STANDARD_WRAP_DATE,
)

_invoice_counter = itertools.count(1)
_fein_counter = itertools.count(1)
_tax_id_counter = itertools.count(100)


def create_program_payload(**overrides) -> dict:
    """JurisdictionProgram registration; defaults are the standard GA program."""
    payload = dict(GA_PROGRAM_DEFAULTS)
    payload.update(overrides)
    return payload


def create_production_company_payload(**overrides) -> dict:
    n = next(_fein_counter)
    payload = {
        "legal_name": "Peachtree Pictures LLC",
        "fein": f"58-10{n:05d}",
        "contact_email": "ops@peachtree.example",
    }
    payload.update(overrides)
    return payload


def create_production_payload(production_company_id, **overrides) -> dict:
    payload = {
        "production_company_id": production_company_id,
        "title": "Atlantic Crossing",
        "production_type": "FEATURE",
        "scheduled_start_date": STANDARD_START_DATE,
        "scheduled_wrap_date": STANDARD_WRAP_DATE,
        "total_budget_cents": 400_000_000,
    }
    payload.update(overrides)
    return payload


def create_credit_buyer_payload(**overrides) -> dict:
    n = next(_tax_id_counter)
    payload = {
        "legal_name": "Magnolia Utilities Corp",
        "tax_id": f"82-44{n:05d}",
        "contact_email": "tax@magnolia.example",
    }
    payload.update(overrides)
    return payload


def create_application_payload(production_id, jurisdiction_program_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "jurisdiction_program_id": jurisdiction_program_id,
        "estimated_qualified_spend_cents": 250_000_000,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(production_id, **overrides) -> dict:
    n = next(_tax_id_counter)
    payload = {
        "production_id": production_id,
        "legal_name": "Savannah Grip & Electric",
        "tax_id": f"47-22{n:05d}",
        "residency_jurisdiction": "GA",
    }
    payload.update(overrides)
    return payload


def create_spend_entry_payload(application_id, vendor_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "vendor_id": vendor_id,
        "external_invoice_ref": f"INV-AUTO-{next(_invoice_counter):05d}",
        "category": "BTL",
        "spend_date": "2026-10-05T00:00:00Z",
        "amount_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def create_audit_package_payload(application_id, **overrides) -> dict:
    payload = {"application_id": application_id}
    payload.update(overrides)
    return payload


def attest_payload(attested_atl_cents, attested_btl_cents, documentation_complete=True) -> dict:
    return {
        "attested_atl_cents": attested_atl_cents,
        "attested_btl_cents": attested_btl_cents,
        "documentation_complete": documentation_complete,
    }


def create_transfer_payload(certificate_id, buyer_id, expected_certificate_version,
                            **overrides) -> dict:
    payload = {
        "certificate_id": certificate_id,
        "buyer_id": buyer_id,
        "amount_cents": 5_000_000,
        "price_cents": 4_500_000,
        "expected_certificate_version": expected_certificate_version,
    }
    payload.update(overrides)
    return payload


def create_clawback_case_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "trigger_reason": "SPEND_SHORTFALL",
        "penalty_mode": "SIMPLE",
    }
    payload.update(overrides)
    return payload
