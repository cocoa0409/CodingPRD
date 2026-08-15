"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "CLIENT_NAME": "Test Client",
    "CLIENT_LANG": "es",
    "CLIENT_DOB": "1990-01-01",
    "STAFF_NAME": "Staff Member",
    "ORG_NAME": "Partner Org",
    "ORG_EMAIL": "contact@org.test",
    "ROOM_NAME": "Room 1",
    "PLAN_TITLE": "Service Plan",
    "NOTE_BODY": "Case note body",
    "PROGRAM_NAME": "ESOL Level 1",
    "SESSION_TITLE": "Orientation",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "preferred_language": DEFAULTS["CLIENT_LANG"],
        "date_of_birth": DEFAULTS["CLIENT_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STAFF_NAME"],
        "role_level": "CASE_MANAGER",
        "clearance_level": 2,
        "weekly_appointment_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ORG_NAME"],
        "service_categories": ["HOUSING"],
        "referral_capacity": 5,
        "contact_email": DEFAULTS["ORG_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["ROOM_NAME"], "capacity": 20}
    defaults.update(overrides)
    return defaults


def create_case_payload(client_id, assigned_manager_id, **overrides) -> dict:
    defaults = {"client_id": client_id, "assigned_manager_id": assigned_manager_id}
    defaults.update(overrides)
    return defaults


def create_assessment_payload(case_id, score=1, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "housing_score": score,
        "employment_score": score,
        "education_score": score,
        "language_score": score,
        "health_score": score,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(title=None, budgeted_hours=5, expected_case_version=1, **overrides) -> dict:
    defaults = {
        "title": title or DEFAULTS["PLAN_TITLE"],
        "budgeted_hours": budgeted_hours,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_case_note_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "body": DEFAULTS["NOTE_BODY"],
        "sensitivity": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(client_id, scope, **overrides) -> dict:
    defaults = {"client_id": client_id, "scope": scope}
    defaults.update(overrides)
    return defaults


def create_referral_payload(case_id, organization_id, service_category, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "organization_id": organization_id,
        "service_category": service_category,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(case_id, advocate_id, kind="DOCUMENT_ID",
                               starts_at="2026-08-10T10:00:00Z",
                               ends_at="2026-08-10T11:00:00Z", **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "advocate_id": advocate_id,
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "kind": "ESOL",
        "capacity": 5,
        "base_fee_cents": 0,
        "cost_per_completion_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_program_enrollment_payload(case_id, program_id, **overrides) -> dict:
    defaults = {"case_id": case_id, "program_id": program_id}
    defaults.update(overrides)
    return defaults


def create_workshop_session_payload(room_id, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "title": DEFAULTS["SESSION_TITLE"],
        "capacity": 5,
        "starts_at": "2026-08-20T10:00:00Z",
        "ends_at": "2026-08-20T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_workshop_enrollment_payload(session_id, case_id, **overrides) -> dict:
    defaults = {"session_id": session_id, "case_id": case_id}
    defaults.update(overrides)
    return defaults


def create_benefit_screening_payload(case_id, stated_annual_income_cents=1000000, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "stated_annual_income_cents": stated_annual_income_cents,
    }
    defaults.update(overrides)
    return defaults


def create_funder_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "funding_streams": [{"stream_name": "City", "share_pct": 100}],
    }
    defaults.update(overrides)
    return defaults
