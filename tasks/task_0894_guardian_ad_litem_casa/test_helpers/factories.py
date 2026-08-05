"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "VOLUNTEER_NAME": "Val One",
    "VOLUNTEER_EMAIL": "v1@casa.org",
    "HOME_ZIP": "94601",
    "SUPERVISOR_NAME": "Sup One",
    "SUPERVISOR_EMAIL": "s1@casa.org",
    "CHILD_INITIALS": "J.D.",
    "CHILD_DOB": "2018-04-01",
    "JURISDICTION": "CA-ALAMEDA",
    "MODULE_NAME": "CORE",
    "COMPLETED_AT": "2026-06-01T00:00:00Z",
    "PERIOD_MONTH": "2026-06",
}


def create_volunteer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["VOLUNTEER_NAME"],
        "email": DEFAULTS["VOLUNTEER_EMAIL"],
        "home_zip": DEFAULTS["HOME_ZIP"],
    }
    payload.update(overrides)
    return payload


def create_supervisor_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["SUPERVISOR_NAME"],
        "email": DEFAULTS["SUPERVISOR_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_case_payload(supervisor_id, **overrides) -> dict:
    payload = {
        "child_initials": DEFAULTS["CHILD_INITIALS"],
        "child_dob": DEFAULTS["CHILD_DOB"],
        "jurisdiction": DEFAULTS["JURISDICTION"],
        "supervisor_id": supervisor_id,
    }
    payload.update(overrides)
    return payload


def create_background_check_payload(**overrides) -> dict:
    payload = {"check_type": "STATE_AND_FEDERAL"}
    payload.update(overrides)
    return payload


def create_training_record_payload(**overrides) -> dict:
    payload = {
        "module_name": DEFAULTS["MODULE_NAME"],
        "hours": 30,
        "completed_at": DEFAULTS["COMPLETED_AT"],
    }
    payload.update(overrides)
    return payload


def create_visit_payload(**overrides) -> dict:
    payload = {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-06-05T10:00:00Z",
        "contact_end": "2026-06-05T11:00:00Z",
        "miles": 0,
    }
    payload.update(overrides)
    return payload


def create_hearing_payload(**overrides) -> dict:
    payload = {
        "hearing_type": "STATUS",
        "scheduled_at": "2026-07-20T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_court_report_payload(hearing_id, **overrides) -> dict:
    payload = {
        "hearing_id": hearing_id,
        "content_summary": "Narrative of the child's situation.",
        "recommendation": "Maintain current placement.",
    }
    payload.update(overrides)
    return payload


def create_expense_claim_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "period_month": DEFAULTS["PERIOD_MONTH"],
        "total_miles": 120,
        "other_expense_cents": 6000,
    }
    payload.update(overrides)
    return payload
