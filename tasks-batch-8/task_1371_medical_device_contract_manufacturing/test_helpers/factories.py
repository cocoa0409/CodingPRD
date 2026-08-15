"""Payload factories — one per entity, input fields only."""
from .constants import (
    AGREEMENT_FROM,
    AGREEMENT_TO,
    MFG_DEFAULT,
    PROTOCOL_WINDOW_END,
    PROTOCOL_WINDOW_START,
    UDI_VALID,
)


def create_dmr_payload(**overrides) -> dict:
    defaults = {
        "device_code": "DEV-1",
        "revision_code": "A",
        "sterile": True,
        "shelf_life_claim_months": 20,
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "L-1",
        "description": "",
        "changeover_buffer_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": "SUP-1",
        "name": "Test Supplier",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(expected_supplier_version, **overrides) -> dict:
    defaults = {
        "agreement_code": "QA-1",
        "audit_rights_granted": True,
        "audit_notice_days": 30,
        "change_notice_days": 90,
        "effective_from": AGREEMENT_FROM,
        "effective_to": AGREEMENT_TO,
        "expected_supplier_version": expected_supplier_version,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "part_number": "PN-1",
        "description": "component",
        "critical": False,
    }
    defaults.update(overrides)
    return defaults


def create_receive_payload(**overrides) -> dict:
    defaults = {"quantity": 100}
    defaults.update(overrides)
    return defaults


def create_scn_payload(**overrides) -> dict:
    defaults = {
        "change_description": "process change",
        "impact_class": "MINOR",
        "proposed_effective_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-09-10T00:00:00Z",
        "scheduled_end": "2026-09-11T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_completion_payload(**overrides) -> dict:
    defaults = {"findings_count": 0, "major_findings_count": 0}
    defaults.update(overrides)
    return defaults


def create_protocol_payload(dmr_id, line_id, **overrides) -> dict:
    defaults = {
        "protocol_code": "VP-1",
        "dmr_id": dmr_id,
        "line_id": line_id,
        "planned_start": PROTOCOL_WINDOW_START,
        "planned_end": PROTOCOL_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_study_payload(dmr_id, **overrides) -> dict:
    defaults = {
        "dmr_id": dmr_id,
        "study_type": "ACCELERATED",
        "claimed_months": 20,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(dmr_id, protocol_id, **overrides) -> dict:
    defaults = {
        "lot_number": "LT-1",
        "dmr_id": dmr_id,
        "validation_protocol_id": protocol_id,
        "quantity": 10,
        "manufactured_at": MFG_DEFAULT,
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(part_id, **overrides) -> dict:
    defaults = {
        "supplier_part_id": part_id,
        "quantity_used": 10,
        "supplier_lot_number": "SL-1",
    }
    defaults.update(overrides)
    return defaults


def create_label_payload(**overrides) -> dict:
    defaults = {"udi_di": UDI_VALID}
    defaults.update(overrides)
    return defaults


def create_sterility_payload(**overrides) -> dict:
    defaults = {"result": "PASSED"}
    defaults.update(overrides)
    return defaults


def create_ncr_payload(**overrides) -> dict:
    defaults = {
        "ncr_code": "NCR-1",
        "description": "nonconformance",
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(**overrides) -> dict:
    defaults = {"disposition": "REWORK", "fault": "INTERNAL"}
    defaults.update(overrides)
    return defaults


def create_complaint_payload(lot_id, **overrides) -> dict:
    defaults = {
        "complaint_code": "CMP-1",
        "lot_id": lot_id,
        "severity": "MINOR",
        "description": "field complaint",
    }
    defaults.update(overrides)
    return defaults


def create_capa_payload(dmr_id, **overrides) -> dict:
    defaults = {
        "capa_code": "CAPA-1",
        "dmr_id": dmr_id,
        "source_type": "MANUAL",
        "process_change": False,
    }
    defaults.update(overrides)
    return defaults


def create_field_action_payload(dmr_id, reason_complaint_id, **overrides) -> dict:
    defaults = {
        "action_code": "FA-1",
        "dmr_id": dmr_id,
        "action_type": "REMOVAL",
        "scope_mfg_start": "2026-08-01T00:00:00Z",
        "scope_mfg_end": "2026-08-31T23:59:59Z",
        "reason_complaint_id": reason_complaint_id,
    }
    defaults.update(overrides)
    return defaults


def create_revision_payload(expected_dmr_version, **overrides) -> dict:
    defaults = {
        "revision_code": "B",
        "shelf_life_claim_months": 24,
        "sterile": True,
        "expected_dmr_version": expected_dmr_version,
    }
    defaults.update(overrides)
    return defaults
