"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import uuid

from .constants import (
    CERT_FAR_EXPIRY,
    DEFAULT_FC_PSI,
    DEFAULT_WORK_DATE,
    MODIFIED_MAX_DENSITY_PCF,
    STANDARD_MAX_DENSITY_PCF,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Project",
        "permit_number": _uniq("P"),
        "jurisdiction": "City A",
        "contractor_name": "GC Co",
        "building_official_name": "BO Smith",
    }
    defaults.update(overrides)
    return defaults


def soil_scope_item(**overrides) -> dict:
    defaults = {
        "test_method": "SOIL_COMPACTION",
        "description": "pad",
        "required_cert_level": 1,
        "required_count": 1,
        "proctor_method": "STANDARD",
        "standard_max_density_pcf": STANDARD_MAX_DENSITY_PCF,
        "modified_max_density_pcf": MODIFIED_MAX_DENSITY_PCF,
    }
    defaults.update(overrides)
    return defaults


def concrete_scope_item(**overrides) -> dict:
    defaults = {
        "test_method": "CONCRETE_STRENGTH",
        "description": "footings",
        "required_cert_level": 1,
        "required_count": 1,
    }
    defaults.update(overrides)
    return defaults


def weld_scope_item(**overrides) -> dict:
    defaults = {
        "test_method": "WELD_VISUAL",
        "description": "frames",
        "required_cert_level": 1,
        "required_count": 1,
    }
    defaults.update(overrides)
    return defaults


def bolt_scope_item(**overrides) -> dict:
    defaults = {
        "test_method": "BOLT_TENSION",
        "description": "splices",
        "required_cert_level": 1,
        "required_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_ssi_revision_payload(scope_items, specified_fc_psi=DEFAULT_FC_PSI,
                                acceptance_method_concrete=None) -> dict:
    payload = {"specified_fc_psi": specified_fc_psi, "scope_items": scope_items}
    if acceptance_method_concrete is not None:
        payload["acceptance_method_concrete"] = acceptance_method_concrete
    return payload


def approve_decision_payload(decision, expected_project_version) -> dict:
    return {"decision": decision, "expected_project_version": expected_project_version}


def certification_entry(method, level=2, expires_at=CERT_FAR_EXPIRY) -> dict:
    return {"method": method, "level": level, "expires_at": expires_at}


def create_technician_payload(certifications=None, **overrides) -> dict:
    defaults = {"full_name": "Tech One", "employee_code": _uniq("T")}
    defaults.update(overrides)
    if certifications is not None:
        defaults["certifications"] = certifications
    return defaults


def append_certification_payload(method, level, expires_at) -> dict:
    return {"method": method, "level": level, "expires_at": expires_at}


def create_assignment_payload(project_id, scope_item_id, technician_id,
                              work_date=DEFAULT_WORK_DATE,
                              start_time="09:00", end_time="10:00") -> dict:
    return {
        "project_id": project_id,
        "scope_item_id": scope_item_id,
        "technician_id": technician_id,
        "work_date": work_date,
        "start_time": start_time,
        "end_time": end_time,
    }


def create_field_test_payload(assignment_id, measured_values) -> dict:
    return {"assignment_id": assignment_id, "measured_values": measured_values}


def create_lab_payload(**overrides) -> dict:
    defaults = {"name": "Lab One", "lab_code": _uniq("L"), "daily_break_capacity": 10}
    defaults.update(overrides)
    return defaults


def create_lab_sample_payload(assignment_id, lab_id, cast_at, required_break_age_days) -> dict:
    return {
        "assignment_id": assignment_id,
        "lab_id": lab_id,
        "cast_at": cast_at,
        "required_break_age_days": required_break_age_days,
    }


def schedule_break_payload(break_scheduled_date) -> dict:
    return {"break_scheduled_date": break_scheduled_date}


def record_break_payload(broken_at, cylinder_strengths_psi) -> dict:
    return {"broken_at": broken_at, "cylinder_strengths_psi": cylinder_strengths_psi}


def submit_correction_payload(correction_note) -> dict:
    return {"correction_note": correction_note}


def verify_ncr_payload(outcome, verification_note=None, evidence_field_test_id=None) -> dict:
    payload = {"outcome": outcome}
    if verification_note is not None:
        payload["verification_note"] = verification_note
    if evidence_field_test_id is not None:
        payload["evidence_field_test_id"] = evidence_field_test_id
    return payload


def create_daily_report_payload(project_id, report_date, assignment_ids, summary) -> dict:
    return {
        "project_id": project_id,
        "report_date": report_date,
        "assignment_ids": assignment_ids,
        "summary": summary,
    }


def create_discrepancy_payload(project_id, subject, description, routed_to,
                               scope_item_id=None) -> dict:
    payload = {
        "project_id": project_id,
        "subject": subject,
        "description": description,
        "routed_to": routed_to,
    }
    if scope_item_id is not None:
        payload["scope_item_id"] = scope_item_id
    return payload


def respond_discrepancy_payload(response_text) -> dict:
    return {"response_text": response_text}


def resolve_discrepancy_payload(outcome) -> dict:
    return {"outcome": outcome}


def void_letter_payload(void_reason) -> dict:
    return {"void_reason": void_reason}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
