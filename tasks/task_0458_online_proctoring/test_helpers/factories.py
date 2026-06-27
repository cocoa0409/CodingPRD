"""Payload factories — one per entity, input fields only (Online Proctoring PRD §3)."""

DEFAULTS = {
    "INSTITUTION_NAME": "Test Institution",
    "PROCTOR_NAME": "Test Proctor",
    "CANDIDATE_NAME": "Test Candidate",
    "EXAM_TITLE": "Test Exam",
    "BASE_DURATION_MINUTES": 60,
    "WINDOW_START_UTC": "2026-07-01T08:00:00Z",
    "WINDOW_END_UTC": "2026-07-01T23:00:00Z",
    "MONITORING_MODE": "LIVE",
    "CONCURRENT_CAPACITY": 4,
}


def create_institution_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["INSTITUTION_NAME"]}
    defaults.update(overrides)
    return defaults


def create_proctor_payload(institution_id: str, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "full_name": DEFAULTS["PROCTOR_NAME"],
        "concurrent_capacity": DEFAULTS["CONCURRENT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(institution_id: str, email: str, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "full_name": DEFAULTS["CANDIDATE_NAME"],
        "email": email,
    }
    defaults.update(overrides)
    return defaults


def create_exam_payload(institution_id: str, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "title": DEFAULTS["EXAM_TITLE"],
        "base_duration_minutes": DEFAULTS["BASE_DURATION_MINUTES"],
        "window_start_utc": DEFAULTS["WINDOW_START_UTC"],
        "window_end_utc": DEFAULTS["WINDOW_END_UTC"],
        "monitoring_mode": DEFAULTS["MONITORING_MODE"],
        "lockdown_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_payload(candidate_id: str, exam_id: str, **overrides) -> dict:
    defaults = {"candidate_id": candidate_id, "exam_id": exam_id}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(exam_id: str, candidate_id: str, proctor_id: str,
                               scheduled_start_utc: str, **overrides) -> dict:
    defaults = {
        "exam_id": exam_id,
        "candidate_id": candidate_id,
        "proctor_id": proctor_id,
        "scheduled_start_utc": scheduled_start_utc,
    }
    defaults.update(overrides)
    return defaults


def create_identity_verification_payload(photo_id_match: bool, room_scan_clear: bool) -> dict:
    return {"photo_id_match": photo_id_match, "room_scan_clear": room_scan_clear}


def create_incident_flag_payload(kind: str, severity: str) -> dict:
    return {"kind": kind, "severity": severity}


def create_escalation_payload(session_id: str, incident_flag_id: str) -> dict:
    return {"session_id": session_id, "incident_flag_id": incident_flag_id}


def create_decide_payload(verdict: str, expected_escalation_version: int) -> dict:
    return {"verdict": verdict, "expected_escalation_version": expected_escalation_version}


def create_integrity_report_payload(institution_id: str, candidate_id: str,
                                    exam_id: str, session_ids: list) -> dict:
    return {
        "institution_id": institution_id,
        "candidate_id": candidate_id,
        "exam_id": exam_id,
        "session_ids": session_ids,
    }


def create_retake_authorization_payload(voided_session_id: str) -> dict:
    return {"voided_session_id": voided_session_id}


def create_rebook_payload(proctor_id: str, scheduled_start_utc: str,
                          expected_appointment_version, **overrides) -> dict:
    defaults = {
        "proctor_id": proctor_id,
        "scheduled_start_utc": scheduled_start_utc,
        "expected_appointment_version": expected_appointment_version,
    }
    defaults.update(overrides)
    return defaults
