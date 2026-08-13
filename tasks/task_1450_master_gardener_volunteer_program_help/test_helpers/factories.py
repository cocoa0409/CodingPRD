"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "year_label": TEST_DEFAULTS["YEAR_LABEL"],
        "start_date": TEST_DEFAULTS["START_DATE"],
        "end_date": TEST_DEFAULTS["END_DATE"],
        "admission_capacity": TEST_DEFAULTS["ADMISSION_CAPACITY"],
        "hour_requirement": TEST_DEFAULTS["HOUR_REQUIREMENT"],
        "ce_requirement": TEST_DEFAULTS["CE_REQUIREMENT"],
        "training_module_count": TEST_DEFAULTS["TRAINING_MODULE_COUNT"],
        "training_pass_quiz_average": TEST_DEFAULTS["TRAINING_PASS_QUIZ_AVERAGE"],
        "training_capacity": TEST_DEFAULTS["TRAINING_CAPACITY"],
        "recert_opens_at": TEST_DEFAULTS["RECERT_OPENS_AT"],
        "priority_counties": [],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "applicant_name": "Alice Arbor",
        "email": "alice@example.org",
        "county": "Harford",
        "prior_gardening_years": 7,
    }
    defaults.update(overrides)
    return defaults


def score_application_payload(**overrides) -> dict:
    defaults = {"essay_score": 80, "interview_score": 90}
    defaults.update(overrides)
    return defaults


def decide_application_payload(decision="ACCEPT") -> dict:
    return {"decision": decision}


def create_enrollment_payload(cycle_id, volunteer_id) -> dict:
    return {"cycle_id": cycle_id, "volunteer_id": volunteer_id}


def progress_payload(modules_completed=5, quiz_average=85.0) -> dict:
    return {"modules_completed": modules_completed,
            "quiz_average": quiz_average}


def create_credit_entry_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "entry_kind": "SERVICE",
        "activity_type": "OTHER",
        "activity_date": "2026-08-05",
        "hours": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_ce_entry_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "entry_kind": "CONTINUING_ED",
        "activity_date": "2026-09-01",
        "hours": 4.0,
        "provider": "Extension College",
        "title": "Soil Science",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "kind": "HELP_DESK",
        "location": "Desk A",
        "start_time": "2026-08-20T09:00:00Z",
        "end_time": "2026-08-20T12:00:00Z",
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_signup_payload(volunteer_id) -> dict:
    return {"volunteer_id": volunteer_id}


def create_inquiry_payload(volunteer_id, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "subject": "Aphids on kale",
        "contact_name": "Resident One",
        "details": "Gray aphid cluster on kale",
    }
    defaults.update(overrides)
    return defaults


def triage_payload(category="PEST") -> dict:
    return {"category": category}


def create_specialist_payload(**overrides) -> dict:
    defaults = {
        "name": "Dr. Pest",
        "specialty": "PEST",
        "max_concurrent_referrals": 3,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(cycle_id, organizer_volunteer_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "organizer_volunteer_id": organizer_volunteer_id,
        "title": "Pollinator Garden",
        "description": "Install pollinator beds",
        "estimated_hours_per_volunteer": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_rotation_assignment_payload(bed_code, volunteer_id,
                                       week_start) -> dict:
    return {"bed_code": bed_code, "volunteer_id": volunteer_id,
            "week_start": week_start}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
