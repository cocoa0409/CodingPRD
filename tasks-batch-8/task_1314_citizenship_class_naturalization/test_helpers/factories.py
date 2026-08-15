"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""

# Standard screening inputs that compute to ELIGIBLE under the §3.2 cascade and give
# an attained readiness of 80 (25 residence + 25 presence + 15 english + 5 civics + 10
# legal-clear) under the §3.3 formula.
STANDARD_ELIGIBLE_SCREENING = {
    "marital_to_citizen": False,
    "lpr_months": 80,
    "continuous_residence_months": 61,
    "physical_presence_days": 1000,
    "age_years": 40,
    "english_level": 3,
    "civics_practice_pct": 25,
    "has_legal_flag": False,
}


def create_program_payload(**overrides) -> dict:
    defaults = {"name": "Main"}
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ana Paz",
        "email": "ana@example.org",
        "date_of_birth": "1986-04-02",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(expected_applicant_version, **overrides) -> dict:
    defaults = dict(STANDARD_ELIGIBLE_SCREENING)
    defaults.update(overrides)
    defaults["expected_applicant_version"] = expected_applicant_version
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Vic Torres",
        "email": "vic@example.org",
        "background_check_cleared": True,
    }
    defaults.update(overrides)
    return defaults


def create_training_credit_payload(**overrides) -> dict:
    defaults = {"topic": "civics", "hours": 10, "earned_at": "2026-07-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_class_section_payload(instructor_volunteer_id, **overrides) -> dict:
    defaults = {
        "title": "Civics Class",
        "weekday": "MON",
        "start_minute": 600,
        "end_minute": 660,
        "room_id": "R1",
        "instructor_volunteer_id": instructor_volunteer_id,
        "capacity": 2,
        "total_sessions": 10,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(applicant_id, class_section_id, expected_section_version) -> dict:
    return {
        "applicant_id": applicant_id,
        "class_section_id": class_section_id,
        "expected_section_version": expected_section_version,
    }


def create_attendance_payload(session_index, outcome) -> dict:
    return {"session_index": session_index, "outcome": outcome}


def create_workshop_payload(supervising_volunteer_id, **overrides) -> dict:
    defaults = {
        "title": "N-400 Workshop",
        "supervising_volunteer_id": supervising_volunteer_id,
        "scheduled_start": "2026-08-05T10:00:00Z",
        "duration_hours": 3,
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_seat_payload(applicant_id, expected_workshop_version) -> dict:
    return {
        "applicant_id": applicant_id,
        "expected_workshop_version": expected_workshop_version,
    }


def create_packet_payload(workshop_seat_id, prepared_by_volunteer_id, **overrides) -> dict:
    defaults = {
        "workshop_seat_id": workshop_seat_id,
        "prepared_by_volunteer_id": prepared_by_volunteer_id,
    }
    defaults.update(overrides)
    return defaults


def create_fee_waiver_payload(**overrides) -> dict:
    defaults = {
        "household_size": 1,
        "self_reported_income_cents": 1000000,
        "self_reported_benefit": False,
    }
    defaults.update(overrides)
    return defaults


def create_mock_interview_payload(applicant_id, volunteer_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "volunteer_id": volunteer_id,
        "scheduled_start": "2026-08-10T10:00:00Z",
        "duration_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_oath_ceremony_payload(**overrides) -> dict:
    defaults = {
        "ceremony_date": "2026-09-01T17:00:00Z",
        "venue": "City Hall",
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults
