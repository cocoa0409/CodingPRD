"""Payload factories — one per entity, client-input fields only (PRD §3)."""

DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "PROJECT_LOCATION": "Seattle",
    "ANNUAL_HOURS": 100000,
    "WORKER_NAME": "Test Worker",
    "COMPANY_NAME": "Test Subcontractor LLC",
    "TRADE": "general",
    "TOPICS": "daily plan",
    "TASK_DESCRIPTION": "task under analysis",
    "HAZARDS": "identified hazards",
    "CONTROLS": "planned controls",
    "FINDINGS": "findings recorded",
    "DEFICIENCY_DESCRIPTION": "deficiency observed",
    "INCIDENT_DESCRIPTION": "incident reported",
    "SUSPENSION_REASON": "safety stand-down",
}


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "location": DEFAULTS["PROJECT_LOCATION"],
        "annual_hours_worked": DEFAULTS["ANNUAL_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_safety_plan_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "effective_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "full_name": DEFAULTS["WORKER_NAME"],
        "employer_type": "DIRECT",
    }
    defaults.update(overrides)
    if defaults.get("employer_type") == "DIRECT":
        # PRD §3.2: subcontractor_id must be null for DIRECT — omit the key.
        defaults.pop("subcontractor_id", None)
    return defaults


def create_certificate_payload(worker_id, **overrides) -> dict:
    defaults = {
        "worker_id": worker_id,
        "cert_type": "OSHA_10",
        "issued_date": "2026-07-01",
        "expires_date": "2027-07-01",
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "company_name": DEFAULTS["COMPANY_NAME"],
        "trade": DEFAULTS["TRADE"],
    }
    defaults.update(overrides)
    return defaults


def create_huddle_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "huddle_date": "2026-08-01",
        "topics": DEFAULTS["TOPICS"],
    }
    defaults.update(overrides)
    return defaults


def create_jha_payload(project_id, huddle_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "huddle_id": huddle_id,
        "task_description": DEFAULTS["TASK_DESCRIPTION"],
        "hazards": DEFAULTS["HAZARDS"],
        "controls": DEFAULTS["CONTROLS"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "inspection_type": "WEEKLY",
        "due_date": "2026-08-10T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_deficiency_payload(inspection_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "description": DEFAULTS["DEFICIENCY_DESCRIPTION"],
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "incident_type": "INJURY",
        "severity": "SERIOUS",
        "occurred_at": "2026-08-02T08:00:00Z",
        "work_related": True,
        "description": DEFAULTS["INCIDENT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id, jha_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "jha_id": jha_id,
        "permit_type": "FALL_PROTECTION",
        "work_start": "2026-08-02T08:00:00Z",
        "work_end": "2026-08-02T16:00:00Z",
        "authorized_worker_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_drug_test_payload(worker_id, **overrides) -> dict:
    defaults = {
        "worker_id": worker_id,
        "test_type": "RANDOM",
        "collected_at": "2026-08-05T09:00:00Z",
    }
    defaults.update(overrides)
    if defaults.get("test_type") != "POST_INCIDENT":
        # PRD §3.8: incident_id must be null for non-POST_INCIDENT — omit the key.
        defaults.pop("incident_id", None)
    return defaults


def determination_payload(**overrides) -> dict:
    """The five determination flags of PRD §3.6 (defaults all non-recordable)."""
    defaults = {
        "medical_treatment_beyond_first_aid": False,
        "days_away_from_work": 0,
        "restricted_duty": False,
        "loss_of_consciousness": False,
        "significant_diagnosis": False,
    }
    defaults.update(overrides)
    return defaults
