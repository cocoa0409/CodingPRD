"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "FULL_NAME": "Test Employee",
    "JOB_CATEGORY": "NURSE",
    "DEPARTMENT": "ICU",
    "HIRE_DATE": "2025-01-05T00:00:00Z",
    "REQUIRES_RESPIRATOR": False,
    "EXPOSURE_DATETIME": "2026-07-30T10:00:00Z",
    "COMPONENT_COMPLETED_AT": "2026-07-20T09:00:00Z",
    "TITER_RESULTED_AT": "2026-07-22T09:00:00Z",
    "RESTRICTION_START": "2026-08-02T00:00:00Z",
    "INJURY_DATETIME": "2026-07-15T14:00:00Z",
}


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "employee_ref": "E-0001",
        "full_name": DEFAULTS["FULL_NAME"],
        "job_category": DEFAULTS["JOB_CATEGORY"],
        "department": DEFAULTS["DEPARTMENT"],
        "hire_date": DEFAULTS["HIRE_DATE"],
        "requires_respirator": DEFAULTS["REQUIRES_RESPIRATOR"],
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    defaults = {"expected_employee_version": 1}
    defaults.update(overrides)
    return defaults


def complete_component_payload(component="PHYSICAL", **overrides) -> dict:
    defaults = {
        "component": component,
        "completed_at": DEFAULTS["COMPONENT_COMPLETED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_titer_payload(**overrides) -> dict:
    defaults = {
        "disease": "HEP_B",
        "assay_type": "QUANTITATIVE",
        "numeric_value": 15.0,
        "resulted_at": DEFAULTS["TITER_RESULTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {"cycle_year": 2026, "cycle_mode": "CALENDAR_YEAR"}
    defaults.update(overrides)
    return defaults


def cycle_completion_payload(requirement_type="TB_SCREENING", **overrides) -> dict:
    defaults = {
        "requirement_type": requirement_type,
        "completed_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_exposure_case_payload(**overrides) -> dict:
    defaults = {
        "exposure_type": "PERCUTANEOUS",
        "exposure_datetime": DEFAULTS["EXPOSURE_DATETIME"],
        "source_known": False,
        "body_fluid": "BLOOD",
    }
    defaults.update(overrides)
    return defaults


def create_work_restriction_payload(**overrides) -> dict:
    defaults = {
        "restriction_type": "MODIFIED_DUTY",
        "start_date": DEFAULTS["RESTRICTION_START"],
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "index_employee_id": "",
        "disease": "COVID",
        "onset_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def enroll_contact_payload(**overrides) -> dict:
    defaults = {
        "contact_employee_id": "",
        "contact_date": "2026-08-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_injury_payload(**overrides) -> dict:
    defaults = {
        "injury_type": "FALL",
        "injury_datetime": DEFAULTS["INJURY_DATETIME"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "vaccine_type": "INFLUENZA",
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-30T23:59:59Z",
        "department_scope": ["ALL"],
    }
    defaults.update(overrides)
    return defaults
