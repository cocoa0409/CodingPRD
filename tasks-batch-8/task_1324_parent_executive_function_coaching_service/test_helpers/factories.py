"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "ACCOUNT_NAME": "Test Family",
    "PRIMARY_EMAIL": "family@example.com",
    "CLIENT_NAME": "Kid Test",
    "CLIENT_DOB": "2014-01-01",
    "CLIENT_TRACK": "INDIVIDUAL",
    "COACH_NAME": "Coach Test",
    "CREDENTIAL_LEVEL": "CERTIFIED",
    "CONCERNS": "focus and routines",
    "BASELINE_SCORE": 50,
    "CADENCE": "WEEKLY",
    "GOAL_TITLE": "Goal G",
    "GOAL_TARGET_DATE": "2026-09-01",
    "PACKAGE_TRACK": "INDIVIDUAL",
    "CREDITS_TOTAL": 8,
    "CHECKIN_DUE": "2026-08-05T00:00:00Z",
    "CONTACT_NAME": "Dr Test",
    "CONTACT_ORG": "Clinic",
    "CONTACT_TYPE": "CLINICIAN",
    "CONTACT_EMAIL": "contact@clinic.example.com",
    "CONSENT_SCOPE": "FULL_PLAN",
    "CONSENT_EXPIRES": "2027-01-01T00:00:00Z",
    "NOTE_TOPIC": "PROGRESS",
    "NOTE_BODY": "weekly progress note",
    "WORKSHOP_TITLE": "Study Skills",
    "WORKSHOP_CAPACITY": 5,
    "WORKSHOP_PRICE": 15000,
    "WORKSHOP_START": "2026-09-05T17:00:00Z",
    "WORKSHOP_END": "2026-09-05T20:00:00Z",
    "SUPERVISION_SCHEDULED_AT": "2026-08-05T10:00:00Z",
    "SUPERVISION_HOURS": 1.0,
}


def create_family_payload(**overrides) -> dict:
    defaults = {
        "account_name": DEFAULTS["ACCOUNT_NAME"],
        "primary_email": DEFAULTS["PRIMARY_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "date_of_birth": DEFAULTS["CLIENT_DOB"],
        "track": DEFAULTS["CLIENT_TRACK"],
    }
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["COACH_NAME"],
        "credential_level": DEFAULTS["CREDENTIAL_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(**overrides) -> dict:
    defaults = {
        "presenting_concerns": DEFAULTS["CONCERNS"],
        "baseline_score": DEFAULTS["BASELINE_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(coach_id, intake_id, expected_client_version, **overrides) -> dict:
    defaults = {
        "coach_id": coach_id,
        "intake_id": intake_id,
        "cadence": DEFAULTS["CADENCE"],
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["GOAL_TITLE"],
        "target_date": DEFAULTS["GOAL_TARGET_DATE"],
    }
    defaults.update(overrides)
    return defaults


def purchase_package_payload(**overrides) -> dict:
    defaults = {
        "track": DEFAULTS["PACKAGE_TRACK"],
        "credits_total": DEFAULTS["CREDITS_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(package_id, scheduled_start, scheduled_end) -> dict:
    return {
        "package_id": package_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def create_checkin_payload(**overrides) -> dict:
    defaults = {"due_at": DEFAULTS["CHECKIN_DUE"]}
    defaults.update(overrides)
    return defaults


def create_contact_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CONTACT_NAME"],
        "organization": DEFAULTS["CONTACT_ORG"],
        "contact_type": DEFAULTS["CONTACT_TYPE"],
        "email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(contact_id, expected_family_version, **overrides) -> dict:
    defaults = {
        "contact_id": contact_id,
        "scope": DEFAULTS["CONSENT_SCOPE"],
        "expires_at": DEFAULTS["CONSENT_EXPIRES"],
        "expected_family_version": expected_family_version,
    }
    defaults.update(overrides)
    return defaults


def create_note_payload(**overrides) -> dict:
    defaults = {
        "topic": DEFAULTS["NOTE_TOPIC"],
        "body": DEFAULTS["NOTE_BODY"],
    }
    defaults.update(overrides)
    return defaults


def create_workshop_payload(coach_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["WORKSHOP_TITLE"],
        "coach_id": coach_id,
        "capacity": DEFAULTS["WORKSHOP_CAPACITY"],
        "window_start": DEFAULTS["WORKSHOP_START"],
        "window_end": DEFAULTS["WORKSHOP_END"],
        "price_cents": DEFAULTS["WORKSHOP_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(client_id) -> dict:
    return {"client_id": client_id}


def create_supervision_payload(supervisor_coach_id, **overrides) -> dict:
    defaults = {
        "supervisor_coach_id": supervisor_coach_id,
        "scheduled_at": DEFAULTS["SUPERVISION_SCHEDULED_AT"],
        "hours": DEFAULTS["SUPERVISION_HOURS"],
    }
    defaults.update(overrides)
    return defaults
