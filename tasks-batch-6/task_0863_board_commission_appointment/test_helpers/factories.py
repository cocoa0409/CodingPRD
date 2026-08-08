"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_board_payload(**overrides) -> dict:
    defaults = {
        "name": "Zoning Board",
        "jurisdiction": "Springfield",
        "board_type": "COMMISSION",
        "authorized_seat_count": 5,
        "quorum_count": 3,
        "term_length_months": 48,
        "max_consecutive_terms": 2,
        "max_cumulative_years": 12,
        "attendance_threshold_pct": 75.0,
        "sunshine_notice_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_seat_payload(board_id, **overrides) -> dict:
    defaults = {
        "board_id": board_id,
        "seat_number": 1,
        "seat_category": "AT_LARGE",
        "residency_requirement": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_vacancy_payload(seat_id, **overrides) -> dict:
    defaults = {
        "seat_id": seat_id,
        "reason": "NEW_SEAT",
        "application_deadline": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ada Reeves",
        "email": "ada@x.com",
        "residence_district": "D1",
        "resides_in_jurisdiction": True,
        "is_registered_voter": True,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, vacancy_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "vacancy_id": vacancy_id,
        "residency_attested": True,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(application_id, seat_id, term_start_date,
                               expected_seat_version, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "seat_id": seat_id,
        "term_start_date": term_start_date,
        "expected_seat_version": expected_seat_version,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_payload(board_id, scheduled_date, **overrides) -> dict:
    defaults = {
        "board_id": board_id,
        "scheduled_date": scheduled_date,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(term_id, meeting_id, presence, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "meeting_id": meeting_id,
        "presence": presence,
    }
    defaults.update(overrides)
    return defaults


def create_removal_payload(term_id, reason, effective_date, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "reason": reason,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_reappointment_payload(term_id, seat_id, applicant_id,
                                 requested_term_start, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "seat_id": seat_id,
        "applicant_id": applicant_id,
        "requested_term_start": requested_term_start,
    }
    defaults.update(overrides)
    return defaults
