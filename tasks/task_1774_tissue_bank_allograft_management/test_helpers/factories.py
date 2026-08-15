"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "LEGAL_NAME": "Acme Tissue Source",
    "LICENSE_NUMBER": "LIC-001",
    "FREEZER_NAME": "FZ-ULT-1",
    "FREEZER_MIN": -80.0,
    "FREEZER_MAX": -60.0,
    "FREEZER_CAPACITY": 50,
    "DOC_VALID_FROM": "2026-01-01T00:00:00Z",
    "DOC_VALID_TO": "2027-12-31T00:00:00Z",
    "UNIT_COST_CENTS": 5000,
    "UNIT_EXPIRATION": "2027-01-01T00:00:00Z",
    "CASE_START": "2026-08-10T10:00:00Z",
    "CASE_END": "2026-08-10T12:00:00Z",
    "RECALL_WINDOW_START": "2026-01-01T00:00:00Z",
    "RECALL_WINDOW_END": "2026-12-31T00:00:00Z",
}


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "AATB_ACCREDITATION",
        "document_ref": "AATB-1",
        "valid_from": DEFAULTS["DOC_VALID_FROM"],
        "valid_to": DEFAULTS["DOC_VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_freezer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FREEZER_NAME"],
        "min_celsius": DEFAULTS["FREEZER_MIN"],
        "max_celsius": DEFAULTS["FREEZER_MAX"],
        "nominal_capacity": DEFAULTS["FREEZER_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def make_manifest_item(**overrides) -> dict:
    defaults = {
        "tissue_type": "BONE",
        "lot_number": "L1",
        "serial_number": "U-001",
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "expiration_at": DEFAULTS["UNIT_EXPIRATION"],
        "criticality_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(supplier_id, freezer_id, items=None, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "freezer_id": freezer_id,
        "items": items if items is not None else [make_manifest_item()],
    }
    payload.update(overrides)
    return payload


def create_implant_case_payload(**overrides) -> dict:
    defaults = {
        "patient_ref": "P-1",
        "or_room_id": "OR-1",
        "scheduled_start": DEFAULTS["CASE_START"],
        "scheduled_end": DEFAULTS["CASE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(tissue_unit_id, **overrides) -> dict:
    payload = {"tissue_unit_id": tissue_unit_id}
    payload.update(overrides)
    return payload


def create_recall_payload(supplier_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "lot_numbers": ["L1"],
        "received_window_start": DEFAULTS["RECALL_WINDOW_START"],
        "received_window_end": DEFAULTS["RECALL_WINDOW_END"],
        "reason": "Supplier sterility assurance failure",
    }
    defaults.update(overrides)
    return defaults


def create_adverse_reaction_payload(tissue_unit_id, **overrides) -> dict:
    defaults = {
        "tissue_unit_id": tissue_unit_id,
        "reaction_type": "INFECTION",
        "severity": "MAJOR",
        "description": "Post-operative infection at graft site",
    }
    defaults.update(overrides)
    return defaults


def create_par_policy_payload(**overrides) -> dict:
    defaults = {
        "tissue_type": "BONE",
        "par_quantity": 2,
        "max_inventory_value_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults
