"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_allergen_payload(**overrides) -> dict:
    defaults = {
        "code": "PEANUT",
        "display_name": "Peanut",
        "regulatory_class": "MAJOR_9",
    }
    defaults.update(overrides)
    return defaults


def create_production_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "LINE-1",
        "description": "Test line",
        "sanitation_class": "WET_WASH",
    }
    defaults.update(overrides)
    return defaults


def create_matrix_entry_payload(line_id, allergen_id, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "allergen_id": allergen_id,
        "handling": "REQUIRES_CHANGEOVER",
        "changeover_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "P-001",
        "product_name": "Test Product",
        "allergen_set": [],
        "rework_class": "NO_REWORK",
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(line_id, product_id, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "product_id": product_id,
        "planned_start_utc": TEST_DEFAULTS["RUN_START_UTC"],
        "planned_end_utc": TEST_DEFAULTS["RUN_END_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_changeover_procedure_payload(target_allergen_id, **overrides) -> dict:
    defaults = {
        "procedure_code": "COP-TEST-V1",
        "target_allergen_id": target_allergen_id,
        "method": "FULL_WET_WASH",
        "min_swab_zones": TEST_DEFAULTS["MIN_SWAB_ZONES"],
        "atp_action_level_rlu": TEST_DEFAULTS["ATP_ACTION_LEVEL_RLU"],
        "allergen_action_level_ppm": TEST_DEFAULTS["ALLERGEN_ACTION_LEVEL_PPM"],
    }
    defaults.update(overrides)
    return defaults


def create_changeover_payload(line_id, to_run_id, procedure_id, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "from_run_id": None,
        "to_run_id": to_run_id,
        "procedure_id": procedure_id,
        "scheduled_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_swab_result_payload(recorded_by_id, **overrides) -> dict:
    defaults = {
        "zone_code": "Z1",
        "swab_type": "ATP",
        "measured_value": 50,
        "recorded_by_id": recorded_by_id,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "tech_code": "TECH-001",
        "full_name": "Test Technician",
        "certified_allergen_ids": [],
        "certification_expiry_utc": TEST_DEFAULTS["CERT_EXPIRY_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_label_reconciliation_payload(run_id, **overrides) -> dict:
    defaults = {
        "run_id": run_id,
        "printed_label_revision": 1,
        "declared_allergens_on_label": [],
    }
    defaults.update(overrides)
    return defaults


def create_rework_batch_payload(source_run_id, source_product_id, **overrides) -> dict:
    defaults = {
        "source_run_id": source_run_id,
        "source_product_id": source_product_id,
        "quantity_kg": 10,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "incident_type": "LABEL_MISMATCH",
        "severity": "LOW",
        "description": "Test incident",
    }
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(technician_id, auditor_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "auditor_id": auditor_id,
        "finding_type": "PROCEDURE_DEVIATION",
        "severity": "MINOR",
        "corrective_action_due_utc": TEST_DEFAULTS["FINDING_DUE_UTC"],
    }
    defaults.update(overrides)
    return defaults
