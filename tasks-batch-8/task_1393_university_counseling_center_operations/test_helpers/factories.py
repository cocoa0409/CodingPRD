"""Payload factories — one per entity, input fields only (PRD section 4)."""

DEFAULTS = {
    "STUDENT_NUMBER": "S100",
    "FULL_NAME": "Test Student",
    "ENROLLMENT_STATUS": "ENROLLED",
    "FUNDING_MODEL": "STUDENT_FEE",
    "LICENSE_ID": "LIC-1",
    "COUNSELOR_NAME": "Test Counselor",
    "WEEKLY_CAPACITY": 20,
    "MAX_RISK_POINTS": 1000,
    "PHQ9": 10,
    "GAD7": 8,
    "TERM": "2026-FALL",
    "BASE_SESSION_LIMIT": 8,
    "STRIKE_LIMIT": 3,
    "CANCEL_WINDOW_HOURS": 24,
    "PROGRAM_TITLE": "Support Group",
    "MEETING_DAY": "TUE",
    "PROGRAM_START": "2026-09-01T17:00:00Z",
    "WEEKS": 8,
    "RISK_CEILING": "HIGH",
    "COVERAGE_DATE": "2026-08-01",
    "SHIFT_KIND": "WALK_IN",
    "SHIFT_START": "2026-08-01T08:00:00Z",
    "SHIFT_END": "2026-08-01T20:00:00Z",
    "SESSION_START": "2026-08-02T09:00:00Z",
    "DURATION": 60,
    "PRESENTING_BAND": "HIGH",
    "NOTE_BODY": "Confidential clinical narrative.",
    "INSTRUMENT": "PHQ9",
    "PHASE": "BASELINE",
    "SCORE": 10,
    "CANCEL_REASON": "client request",
}


def create_student_payload(**overrides) -> dict:
    defaults = {
        "student_number": DEFAULTS["STUDENT_NUMBER"],
        "full_name": DEFAULTS["FULL_NAME"],
        "enrollment_status": DEFAULTS["ENROLLMENT_STATUS"],
        "funding_model": DEFAULTS["FUNDING_MODEL"],
    }
    defaults.update(overrides)
    return defaults


def create_counselor_payload(**overrides) -> dict:
    defaults = {
        "license_id": DEFAULTS["LICENSE_ID"],
        "full_name": DEFAULTS["COUNSELOR_NAME"],
        "specialties": ["GEN"],
        "weekly_individual_capacity": DEFAULTS["WEEKLY_CAPACITY"],
        "max_caseload_risk_points": DEFAULTS["MAX_RISK_POINTS"],
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(student_id, screener_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "screener_id": screener_id,
        "phq9_score": DEFAULTS["PHQ9"],
        "gad7_score": DEFAULTS["GAD7"],
        "ideation_flag": False,
        "recent_attempt_flag": False,
    }
    defaults.update(overrides)
    return defaults


def complete_intake_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "academic_term": DEFAULTS["TERM"],
        "base_session_limit": DEFAULTS["BASE_SESSION_LIMIT"],
        "no_show_strike_limit": DEFAULTS["STRIKE_LIMIT"],
        "late_cancel_window_hours": DEFAULTS["CANCEL_WINDOW_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def book_session_payload(counselor_id, expected_episode_version, **overrides) -> dict:
    defaults = {
        "counselor_id": counselor_id,
        "starts_at": DEFAULTS["SESSION_START"],
        "duration_minutes": DEFAULTS["DURATION"],
        "expected_episode_version": expected_episode_version,
    }
    defaults.update(overrides)
    return defaults


def create_group_program_payload(facilitator_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PROGRAM_TITLE"],
        "facilitator_id": facilitator_id,
        "capacity": 5,
        "meeting_day": DEFAULTS["MEETING_DAY"],
        "starts_at": DEFAULTS["PROGRAM_START"],
        "weeks": DEFAULTS["WEEKS"],
        "risk_band_ceiling": DEFAULTS["RISK_CEILING"],
    }
    defaults.update(overrides)
    return defaults


def create_crisis_shift_payload(**overrides) -> dict:
    defaults = {
        "coverage_date": DEFAULTS["COVERAGE_DATE"],
        "shift_kind": DEFAULTS["SHIFT_KIND"],
        "starts_at": DEFAULTS["SHIFT_START"],
        "ends_at": DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_crisis_visit_payload(student_id, shift_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "shift_id": shift_id,
        "presenting_risk_band": DEFAULTS["PRESENTING_BAND"],
    }
    defaults.update(overrides)
    return defaults


def create_clinical_note_payload(session_id, author_id, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "author_id": author_id,
        "body": DEFAULTS["NOTE_BODY"],
    }
    defaults.update(overrides)
    return defaults


def create_outcome_measure_payload(episode_id, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "instrument": DEFAULTS["INSTRUMENT"],
        "phase": DEFAULTS["PHASE"],
        "score": DEFAULTS["SCORE"],
    }
    defaults.update(overrides)
    return defaults


def match_referral_payload(**overrides) -> dict:
    defaults = {
        "provider_name": "Community Provider",
        "provider_specialty": "GEN",
    }
    defaults.update(overrides)
    return defaults
