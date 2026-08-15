"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import BASE_LETTER_SECTIONS


def create_unit_payload(**overrides) -> dict:
    defaults = {"name": "ED Main", "category": "EMERGENCY"}
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Staff", "capabilities": ["INVESTIGATOR"]}
    defaults.update(overrides)
    return defaults


def create_holiday_payload(**overrides) -> dict:
    defaults = {"observance_date": "2026-09-07", "name": "Labor Day"}
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "patient_ref": "P-0001",
        "received_at": "2026-08-03T09:00:00.000Z",
        "channel": "PHONE",
        "description": "Patient concern reported at the desk",
        "grievance_category": "OTHER",
    }
    defaults.update(overrides)
    return defaults


def create_classification_decision_payload(**overrides) -> dict:
    defaults = {"decision": "GRIEVANCE", "rationale_code": "INITIAL_INTAKE"}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    return dict(overrides)


def create_note_payload(**overrides) -> dict:
    defaults = {"note_type": "INTERVIEW", "body": "Interview note body"}
    defaults.update(overrides)
    return defaults


def create_submit_findings_payload(**overrides) -> dict:
    defaults = {"care_concern_flag": False, "findings_summary": "Findings documented"}
    defaults.update(overrides)
    return defaults


def create_letter_payload(**overrides) -> dict:
    defaults = {
        "sections": list(BASE_LETTER_SECTIONS),
        "body_summary": "Response letter body summary for the patient",
    }
    defaults.update(overrides)
    return defaults


def create_recovery_action_payload(**overrides) -> dict:
    defaults = {
        "action_type": "MEAL_VOUCHER",
        "value_cents": 1000,
        "justification": "Goodwill gesture for the inconvenience",
    }
    defaults.update(overrides)
    return defaults


def create_escalation_payload(**overrides) -> dict:
    defaults = {"escalation_type": "CARE_CONCERN", "review_track": "COMPLIANCE"}
    defaults.update(overrides)
    return defaults


def create_reportable_event_payload(**overrides) -> dict:
    defaults = {
        "authority_code": "STATE_HEALTH_DEPT",
        "trigger_reason": "ALLEGED_ABUSE",
    }
    defaults.update(overrides)
    return defaults


def create_rounding_session_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-08-03T10:00:00.000Z",
        "end_at": "2026-08-03T12:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_interview_room_payload(**overrides) -> dict:
    defaults = {"name": "Room 101", "location": "Tower 3F"}
    defaults.update(overrides)
    return defaults


def create_interview_booking_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-08-04T10:00:00.000Z",
        "end_at": "2026-08-04T11:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_clock_suspension_payload(**overrides) -> dict:
    defaults = {"reason": "AWAITING_PATIENT"}
    defaults.update(overrides)
    return defaults
