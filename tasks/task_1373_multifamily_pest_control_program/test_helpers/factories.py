"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "PROPERTY_NAME": "Test Community",
    "PROPERTY_ADDRESS": "100 Test Way",
    "VENDOR_NAME": "PestCo",
    "SCOPE_PEST_TYPES": ["ROACHES", "BED_BUGS"],
    "VISITS_PER_MONTH": 4,
    "COVERAGE_PER_INCIDENT_CENTS": 20000,
    "MONTHLY_BUDGET_CENTS": 1000000,
    "CONTRACT_START": "2026-08-01",
    "CONTRACT_END": "2027-07-31",
    "LEASE_START": "2026-08-01",
    "LEASE_END": "2027-07-31",
    "CLAUSE_VERSION": "v2026.1",
    "CHARGEBACK_CAP_CENTS": 100000,
    "TECH_NAME": "T One",
    "RESIDENT_NAME": "R One",
    "RESIDENT_EMAIL": "r1@x.com",
}


def create_property_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["PROPERTY_NAME"], "address": DEFAULTS["PROPERTY_ADDRESS"]}
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "scope_pest_types": list(DEFAULTS["SCOPE_PEST_TYPES"]),
        "visits_per_month": DEFAULTS["VISITS_PER_MONTH"],
        "coverage_per_incident_cents": DEFAULTS["COVERAGE_PER_INCIDENT_CENTS"],
        "heat_treatment_included": True,
        "monthly_budget_cents": DEFAULTS["MONTHLY_BUDGET_CENTS"],
        "start_date": DEFAULTS["CONTRACT_START"],
        "end_date": DEFAULTS["CONTRACT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {"unit_number": "101", "floor": 1, "stack_index": 1, "bedrooms": 1}
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "start_date": DEFAULTS["LEASE_START"],
        "end_date": DEFAULTS["LEASE_END"],
        "pest_addendum_signed": True,
        "chargeback_clause_version": DEFAULTS["CLAUSE_VERSION"],
        "chargeback_cap_cents": DEFAULTS["CHARGEBACK_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["RESIDENT_NAME"],
        "email": DEFAULTS["RESIDENT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {"full_name": DEFAULTS["TECH_NAME"], "vendor_name": DEFAULTS["VENDOR_NAME"]}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "kind": "ROUTINE",
        "pest_type": "ROACHES",
        "scheduled_for": "2026-08-05T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(**overrides) -> dict:
    defaults = {"live_sightings": 0, "evidence_count": 0, "bed_bug_positive": False}
    defaults.update(overrides)
    return defaults


def create_treatment_payload(**overrides) -> dict:
    defaults = {
        "pest_type": "ROACHES",
        "treatment_type": "CHEMICAL",
        "window_start": "2026-08-10T09:00:00Z",
        "window_end": "2026-08-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_disposal_payload(**overrides) -> dict:
    defaults = {"item_description": "mattress", "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_chargeback_payload(**overrides) -> dict:
    defaults = {"kind": "NON_COMPLIANCE_FEE"}
    defaults.update(overrides)
    return defaults


def create_claim_packet_payload(**overrides) -> dict:
    defaults = {"claim_reference": "HC-1", "references": []}
    defaults.update(overrides)
    return defaults
