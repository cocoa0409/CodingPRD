"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": "CA-BOE",
        "name": "California",
        "level": "STATE",
        "return_frequency": "MONTHLY",
        "deposit_frequency": "SEMI_MONTHLY",
    }
    defaults.update(overrides)
    return defaults


def create_product_class_payload(**overrides) -> dict:
    defaults = {
        "code": "DIESEL",
        "description": "Diesel fuel",
        "base_unit": "GALLON",
    }
    defaults.update(overrides)
    return defaults


def create_tax_rate_payload(**overrides) -> dict:
    defaults = {
        "rate_millicents_per_unit": 24300,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rate_change_notice_payload(**overrides) -> dict:
    defaults = {
        "new_rate_millicents_per_unit": 30000,
        "announced_effective_from": "2026-08-01T00:00:00Z",
        "source_reference": "BULL-2026-08",
    }
    defaults.update(overrides)
    return defaults


def create_registrant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Acme Fuels",
        "fein": "12-3456789",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    defaults = {
        "deposit_method": "SAFE_HARBOR",
    }
    defaults.update(overrides)
    return defaults


def create_bond_payload(**overrides) -> dict:
    defaults = {
        "surety_name": "SureCo",
        "principal_amount_cents": 1500000,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_exemption_certificate_payload(**overrides) -> dict:
    defaults = {
        "customer_reference": "CUST-1",
        "certificate_type": "RESALE",
        "valid_from": "2026-03-01T00:00:00Z",
        "valid_to": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bonded_movement_payload(**overrides) -> dict:
    defaults = {
        "quantity_units": 400,
        "origin_facility": "TERM-A",
        "destination_facility": "TERM-B",
    }
    defaults.update(overrides)
    return defaults


def create_taxable_event_payload(**overrides) -> dict:
    defaults = {
        "event_date": "2026-08-03T00:00:00Z",
        "quantity_units": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {
        "period": "2026-08",
    }
    defaults.update(overrides)
    return defaults


def create_credit_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "EXPORT",
        "claimed_cents": 24300,
        "justification": "export docs",
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08",
        "period_end": "2026-08",
    }
    defaults.update(overrides)
    return defaults
