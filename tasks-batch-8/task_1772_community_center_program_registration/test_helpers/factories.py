"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from . import constants as C

DEFAULTS = {
    "SEASON_NAME": "Fall 2026",
    "PROGRAM_NAME": "Youth Basketball",
    "PROGRAM_CATEGORY": "Sports",
    "ROOM_NAME": "Gymnasium A",
    "ROOM_CAPACITY": 50,
    "INSTRUCTOR_NAME": "Jordan Coach",
    "INSTRUCTOR_EMAIL": "coach@example.org",
    "SESSION_TITLE": "Youth Basketball — Tue/Thu 6pm",
    "SESSION_CAPACITY": 5,
    "SESSION_MIN_ENROLLMENT": 1,
    "FEE_RESIDENT_CENTS": 5000,
    "FEE_NONRESIDENT_CENTS": 5000,
    "REVENUE_SHARE_BP": 5000,
    "GUARANTEE_MIN_CENTS": 0,
    "CANCELLATION_GUARANTEE_CENTS": 0,
    "HOUSEHOLD_NAME": "Test Household",
    "PARTICIPANT_NAME": "Test Participant",
    "EMERGENCY_CONTACT_NAME": "Guardian One",
    "EMERGENCY_CONTACT_PHONE": "555-0100",
    "HOUSEHOLD_SIZE": 4,
    "ANNUAL_INCOME_CENTS": 2_500_000,
}


def create_season_payload(**overrides) -> dict:
    """Required season inputs; optional policy knobs only when overridden."""
    payload = {
        "name": DEFAULTS["SEASON_NAME"],
        "start_date": C.SEASON_START,
        "end_date": C.SEASON_END,
        "resident_opens_at": C.RESIDENT_OPENS,
        "general_opens_at": C.GENERAL_OPENS,
        "registration_closes_at": C.REGISTRATION_CLOSES,
    }
    payload.update(overrides)
    return payload


def create_program_payload(season_id: str, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "name": DEFAULTS["PROGRAM_NAME"],
        "category": DEFAULTS["PROGRAM_CATEGORY"],
    }
    payload.update(overrides)
    return payload


def create_room_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ROOM_NAME"],
        "capacity": DEFAULTS["ROOM_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_instructor_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["INSTRUCTOR_NAME"],
        "email": DEFAULTS["INSTRUCTOR_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_class_session_payload(program_id: str, instructor_id: str,
                                 **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "instructor_id": instructor_id,
        "title": DEFAULTS["SESSION_TITLE"],
        "capacity": DEFAULTS["SESSION_CAPACITY"],
        "min_enrollment": DEFAULTS["SESSION_MIN_ENROLLMENT"],
        "fee_resident_cents": DEFAULTS["FEE_RESIDENT_CENTS"],
        "fee_nonresident_cents": DEFAULTS["FEE_NONRESIDENT_CENTS"],
        "enrollment_check_at": C.ENROLLMENT_CHECK_AT,
    }
    payload.update(overrides)
    return payload


def create_class_meeting_payload(session_id: str, room_id: str,
                                 starts_at: str = C.MEETING_START,
                                 ends_at: str = C.MEETING_END) -> dict:
    return {
        "session_id": session_id,
        "room_id": room_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }


def create_instructor_contract_payload(session_id: str, instructor_id: str,
                                       **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "instructor_id": instructor_id,
        "revenue_share_bp": DEFAULTS["REVENUE_SHARE_BP"],
        "guarantee_min_cents": DEFAULTS["GUARANTEE_MIN_CENTS"],
        "cancellation_guarantee_cents": DEFAULTS["CANCELLATION_GUARANTEE_CENTS"],
        "settlement_basis": "ENROLLMENT_BASIS",
    }
    payload.update(overrides)
    return payload


def create_household_payload(**overrides) -> dict:
    payload = {"account_name": DEFAULTS["HOUSEHOLD_NAME"]}
    payload.update(overrides)
    return payload


def create_participant_payload(household_id: str, **overrides) -> dict:
    payload = {
        "household_id": household_id,
        "full_name": DEFAULTS["PARTICIPANT_NAME"],
        "birth_date": C.ADULT_BIRTH_DATE,
    }
    payload.update(overrides)
    return payload


def create_safety_form_payload(participant_id: str, season_id: str, signer_name: str,
                               **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "season_id": season_id,
        "emergency_contact_name": DEFAULTS["EMERGENCY_CONTACT_NAME"],
        "emergency_contact_phone": DEFAULTS["EMERGENCY_CONTACT_PHONE"],
        "signer_name": signer_name,
    }
    payload.update(overrides)
    return payload


def create_scholarship_application_payload(household_id: str, season_id: str,
                                           **overrides) -> dict:
    payload = {
        "household_id": household_id,
        "season_id": season_id,
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_registration_payload(session_id: str, participant_id: str,
                                expected_class_session_version: int) -> dict:
    return {
        "session_id": session_id,
        "participant_id": participant_id,
        "expected_class_session_version": expected_class_session_version,
    }


def create_payment_payload(amount_cents: int, method: str = "EXTERNAL") -> dict:
    return {"amount_cents": amount_cents, "method": method}


def create_attendance_record_payload(meeting_id: str, registration_id: str,
                                     status: str = "PRESENT") -> dict:
    return {
        "meeting_id": meeting_id,
        "registration_id": registration_id,
        "status": status,
    }
