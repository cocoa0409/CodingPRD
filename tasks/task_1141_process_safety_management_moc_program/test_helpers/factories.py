"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

DEFAULTS = {
    "unit_name": "Test Unit",
    "pha_cycle_months": 12,
    "full_name": "Test Person",
    "moc_title": "Test change",
    "moc_description": "Change description",
    "discipline": "CHEMICAL",
    "screening_severity": 2,
    "screening_likelihood": 2,
    "severity_score": 2,
    "likelihood_score": 2,
    "detection_score": 1,
    "method": "HAZOP",
    "initial_validated_at": "2026-04-01",
    "field_window_start": "2026-05-01",
    "field_window_end": "2026-05-05",
    "action_title": "Test action",
    "priority": "P1",
    "file_ref": "s3://evidence/doc.pdf",
    "evidence_description": "Closure evidence",
    "incident_title": "Test incident",
    "severity_class": "HIGH",
    "occurred_at": "2026-04-20",
    "audit_title": "Test audit",
    "document_ref": "SOP-1",
    "requested_days": 30,
    "findings_summary": "Nodes reviewed",
}


_unit_seq = itertools.count(1)


def create_unit_payload(**overrides) -> dict:
    # PRD §3.1: unit_code "must be unique across all units" — a test creating
    # several units without explicit codes would collide on a shared default,
    # so the default is minted unique per call.
    seq = next(_unit_seq)
    defaults = {
        "name": DEFAULTS["unit_name"],
        "unit_code": f"TU-{seq}",
        "pha_cycle_months": DEFAULTS["pha_cycle_months"],
    }
    defaults.update(overrides)
    return defaults


def create_personnel_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["full_name"],
        "employee_ref": DEFAULTS.get("employee_ref", "E-1"),
    }
    defaults.update(overrides)
    return defaults


def create_moc_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["moc_title"],
        "description": DEFAULTS["moc_description"],
        "discipline": DEFAULTS["discipline"],
    }
    defaults.update(overrides)
    return defaults


def classify_payload(**overrides) -> dict:
    defaults = {
        "change_class": "PERMANENT",
        "screening_severity": DEFAULTS["screening_severity"],
        "screening_likelihood": DEFAULTS["screening_likelihood"],
    }
    defaults.update(overrides)
    return defaults


def verdict_payload(**overrides) -> dict:
    defaults = {
        "design_basis_ok": True,
        "codes_standards_ok": True,
        "relief_systems_ok": True,
        "materials_compat_ok": True,
        "severity_score": DEFAULTS["severity_score"],
        "likelihood_score": DEFAULTS["likelihood_score"],
        "detection_score": DEFAULTS["detection_score"],
        "verdict": "ACCEPT",
    }
    defaults.update(overrides)
    return defaults


def create_pha_study_payload(**overrides) -> dict:
    defaults = {
        "method": DEFAULTS["method"],
        "initial_validated_at": DEFAULTS["initial_validated_at"],
    }
    defaults.update(overrides)
    return defaults


def create_pssr_payload(moc_version, **overrides) -> dict:
    defaults = {
        "field_window_start": DEFAULTS["field_window_start"],
        "field_window_end": DEFAULTS["field_window_end"],
        "expected_moc_version": moc_version,
    }
    defaults.update(overrides)
    return defaults


def create_action_item_payload(assignee_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["action_title"],
        "priority": DEFAULTS["priority"],
        "assignee_id": assignee_id,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "file_ref": DEFAULTS["file_ref"],
        "description": DEFAULTS["evidence_description"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(investigator_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["incident_title"],
        "severity_class": DEFAULTS["severity_class"],
        "occurred_at": DEFAULTS["occurred_at"],
        "investigator_id": investigator_id,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(lead_auditor_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["audit_title"],
        "lead_auditor_id": lead_auditor_id,
        "field_window_start": DEFAULTS["field_window_start"],
        "field_window_end": "2026-05-10",
    }
    defaults.update(overrides)
    return defaults


def create_procedure_update_payload(**overrides) -> dict:
    defaults = {"document_ref": DEFAULTS["document_ref"]}
    defaults.update(overrides)
    return defaults


def create_training_assignment_payload(personnel_id, **overrides) -> dict:
    defaults = {"personnel_id": personnel_id}
    defaults.update(overrides)
    return defaults


def create_extension_request_payload(moc_version, **overrides) -> dict:
    defaults = {
        "requested_days": DEFAULTS["requested_days"],
        "expected_moc_version": moc_version,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
