"""Payload factories — one per creatable resource, client-supplied fields only.

Defaults follow the workflow descriptions in PRD section 3; every factory
accepts **overrides so tests control exactly the fields they exercise.
"""
from .constants import TEST_DEFAULTS


def create_facility_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["FACILITY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_system_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "name": TEST_DEFAULTS["SYSTEM_NAME"],
        "design_charge_lbs": TEST_DEFAULTS["DESIGN_CHARGE_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(system_id: str, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "tag_number": "V-101",
        "equipment_type": "VESSEL",
        "inspection_interval_days": 180,
        "inspection_method": "FIXED",
    }
    defaults.update(overrides)
    return defaults


def create_psid_document_payload(system_id: str, expected_system_version,
                                 **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "doc_type": "PID",
        "revision_label": "Rev A",
        "content_uri": "s3://docs/pid-rev-a.pdf",
        "expected_system_version": expected_system_version,
    }
    defaults.update(overrides)
    return defaults


def create_charge_adjustment_payload(facility_id: str, expected_facility_version,
                                     **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "adjustment_type": "ADD",
        "quantity_lbs": 100.0,
        "reason": "charging after pump-out",
        "expected_facility_version": expected_facility_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(equipment_id: str, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "due_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(**overrides) -> dict:
    defaults = {"result": "PASS"}
    defaults.update(overrides)
    return defaults


def create_employee_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "full_name": TEST_DEFAULTS["OPERATOR_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(employee_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "topic": "AMMONIA_OPERATOR",
        "completed_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_drill_event_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "drill_type": "TABLETOP",
        "scheduled_start_at": "2026-09-10T09:00:00Z",
        "scheduled_end_at": "2026-09-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(facility_id: str, reported_by_employee_id: str,
                            **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "severity": "RECORDABLE",
        "description": "ammonia odor near valve",
        "reported_by_employee_id": reported_by_employee_id,
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_payload(incident_id: str, assignee_employee_id: str,
                                     **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "description": "replace compressor gasket",
        "assignee_employee_id": assignee_employee_id,
        "due_at": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_audit_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "scheduled_start_at": "2026-09-15T09:00:00Z",
        "due_at": "2026-10-15T00:00:00Z",
        "lead_auditor": "Alex Auditor",
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "company_name": TEST_DEFAULTS["CONTRACTOR_NAME"],
        "safety_score": TEST_DEFAULTS["SAFETY_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_hot_work_permit_payload(facility_id: str, system_id: str,
                                   contractor_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "system_id": system_id,
        "contractor_id": contractor_id,
        "work_description": "weld repair on discharge line",
        "valid_from": TEST_DEFAULTS["PERMIT_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["PERMIT_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_leak_event_payload(system_id: str, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "estimated_release_lbs": 120.0,
        "source_description": "compressor seal weep",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
