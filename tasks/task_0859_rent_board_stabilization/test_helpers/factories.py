"""Payload factories — one per creatable resource, input fields only.

Field names are PRD-exact. Optional fields are omitted unless overridden.
"""
import itertools

_counter = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}@example.com"


def create_landlord_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Landlord",
        "email": _unique_email("landlord"),
        "business_license_no": "BL-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Tenant",
        "email": _unique_email("tenant"),
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_hearing_officer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Officer",
        "email": _unique_email("officer"),
    }
    defaults.update(overrides)
    return defaults


def create_aga_payload(effective_year: int, aga_pct: float, **overrides) -> dict:
    defaults = {
        "effective_year": effective_year,
        "cpi_pct": aga_pct,
        "aga_pct": aga_pct,
        "effective_from": f"{effective_year}-01-01",
        "effective_to": f"{effective_year}-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(landlord_id: str, **overrides) -> dict:
    defaults = {
        "landlord_id": landlord_id,
        "address": "1 Test St #1",
        "bedrooms": 2,
        "base_rent_cents": 300000,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(registration_year: int, declared_rent_cents: int,
                                expected_unit_version: int, **overrides) -> dict:
    defaults = {
        "registration_year": registration_year,
        "declared_rent_cents": declared_rent_cents,
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def create_rent_adjustment_payload(effective_date: str, proposed_new_rent_cents: int,
                                   apply_banked: bool, expected_unit_version: int,
                                   **overrides) -> dict:
    defaults = {
        "effective_date": effective_date,
        "proposed_new_rent_cents": proposed_new_rent_cents,
        "apply_banked": apply_banked,
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def create_tenancy_payload(unit_id: str, tenant_id: str, start_date: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "start_date": start_date,
    }
    defaults.update(overrides)
    return defaults


def create_petition_payload(unit_id: str, landlord_id: str, petition_type: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "landlord_id": landlord_id,
        "petition_type": petition_type,
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(officer_id: str, scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    defaults = {
        "officer_id": officer_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_service_claim_payload(unit_id: str, tenant_id: str, claim_type: str,
                                 severity: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "claim_type": claim_type,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_buyout_payload(unit_id: str, landlord_id: str, tenant_id: str,
                          offer_amount_cents: int, relocation_amount_cents: int,
                          **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "landlord_id": landlord_id,
        "tenant_id": tenant_id,
        "offer_amount_cents": offer_amount_cents,
        "relocation_amount_cents": relocation_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_exemption_payload(unit_id: str, exemption_type: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "exemption_type": exemption_type,
    }
    defaults.update(overrides)
    return defaults


def create_penalty_payload(unit_id: str, landlord_id: str, penalty_type: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "landlord_id": landlord_id,
        "penalty_type": penalty_type,
    }
    defaults.update(overrides)
    return defaults
