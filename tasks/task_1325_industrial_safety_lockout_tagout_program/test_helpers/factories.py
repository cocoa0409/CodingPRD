"""Payload factories — one per creatable resource, input fields only (PRD §3)."""


def create_machine_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": "A-100",
        "name": "Test Press",
        "area": "Line 1",
        "risk_window_policy": "ROLLING_12MO",
    }
    defaults.update(overrides)
    return defaults


def create_machine_modification_payload(**overrides) -> dict:
    defaults = {
        "description": "Replaced guard interlock",
        "expected_machine_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "employee_no": "E-100",
        "full_name": "Test Employee",
        "qualification": "AUTHORIZED",
    }
    defaults.update(overrides)
    return defaults


def default_energy_sources(count=1) -> list:
    """N distinct energy-source entries (DP-1, VA-2, HY-3, ...)."""
    catalog = [
        {"source_type": "ELECTRICAL", "magnitude": "480V",
         "isolation_point": "DP-1", "dissipation_method": "none"},
        {"source_type": "PNEUMATIC", "magnitude": "120psi",
         "isolation_point": "VA-2", "dissipation_method": "bleed"},
        {"source_type": "HYDRAULIC", "magnitude": "2000psi",
         "isolation_point": "VA-3", "dissipation_method": "accumulator discharge"},
        {"source_type": "GRAVITY", "magnitude": "ram",
         "isolation_point": "BL-4", "dissipation_method": "block"},
    ]
    return catalog[:count]


def create_energy_survey_payload(machine_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "energy_sources": default_energy_sources(1),
    }
    defaults.update(overrides)
    return defaults


def default_steps(count=1) -> list:
    catalog = [
        {"step_no": 1, "action": "Open disconnect", "isolation_point": "DP-1"},
        {"step_no": 2, "action": "Close valve", "isolation_point": "VA-2"},
        {"step_no": 3, "action": "Block ram", "isolation_point": "BL-4"},
    ]
    return catalog[:count]


def create_lockout_procedure_payload(machine_id, survey_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "survey_id": survey_id,
        "steps": default_steps(1),
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "course_code": "LOTO_AUTHORIZED_INITIAL",
        "delivery_mode": "IN_PERSON",
    }
    defaults.update(overrides)
    return defaults


def create_lockout_session_payload(machine_id, procedure_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "procedure_id": procedure_id,
        "session_type": "INDIVIDUAL",
    }
    defaults.update(overrides)
    return defaults


def create_employee_lock_payload(session_id, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "lock_no": "L-1",
        "tag_no": "T-1",
    }
    defaults.update(overrides)
    return defaults


def create_procedure_audit_payload(procedure_id, **overrides) -> dict:
    defaults = {
        "procedure_id": procedure_id,
        "scheduled_start": "2026-09-01T09:00:00Z",
        "scheduled_end": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(machine_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "kind": "NEAR_MISS",
        "occurred_at": "2026-07-01T00:00:00Z",
        "severity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_permit_payload(machine_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "company_name": "Acme Rigging",
        "insurance_valid_until": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_minor_servicing_exception_payload(machine_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "task_description": "Clear jam at infeed",
        "routine_repetitive": True,
        "integral_to_production": True,
        "alternative_measures_effective": True,
        "estimated_duration_min": 30,
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2026-09-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
