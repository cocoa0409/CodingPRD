"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SEASON_NAME": "S1",
    "APPLICATION_OPEN_AT": "2026-05-10T00:00:00Z",
    "APPLICATION_CLOSE_AT": "2026-05-20T00:00:00Z",
    "INTERVIEW_WINDOW_START_AT": "2026-06-01T00:00:00Z",
    "INTERVIEW_WINDOW_END_AT": "2026-06-30T23:59:59Z",
    "OFFER_WINDOW_OPEN_AT": "2026-07-01T00:00:00Z",
    "OFFER_WINDOW_CLOSE_AT": "2026-07-31T23:59:59Z",
    "SHORTLIST_THRESHOLD": 10,
    "STIPEND_BUDGET": 1000000,
    "SCHOOL_NAME": "StateU",
    "TIER": "TARGET",
    "APPLICATION_CAP": 10,
    "STIPEND_REGION": "REGIONAL",
    "EVENT_TYPE": "RESUME_DROP",
    "DAY_START": "2026-06-08T09:00:00Z",
    "DAY_END": "2026-06-08T17:00:00Z",
    "DAY_CAPACITY": 5,
    "SLOT_START": "2026-06-08T10:00:00Z",
    "SLOT_END": "2026-06-08T11:00:00Z",
    "WEEKLY_RATE": 150000,
    "DURATION_WEEKS": 12,
    "RELOCATION_MILES": 100,
    "GRAD_DATE": "2027-05-15T00:00:00Z",
    "PROJECT_TITLE": "Project P",
    "PROJECT_CAPACITY": 2,
}


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SEASON_NAME"],
        "application_open_at": DEFAULTS["APPLICATION_OPEN_AT"],
        "application_close_at": DEFAULTS["APPLICATION_CLOSE_AT"],
        "interview_window_start_at": DEFAULTS["INTERVIEW_WINDOW_START_AT"],
        "interview_window_end_at": DEFAULTS["INTERVIEW_WINDOW_END_AT"],
        "offer_window_open_at": DEFAULTS["OFFER_WINDOW_OPEN_AT"],
        "offer_window_close_at": DEFAULTS["OFFER_WINDOW_CLOSE_AT"],
        "shortlist_score_threshold": DEFAULTS["SHORTLIST_THRESHOLD"],
        "stipend_budget_cents": DEFAULTS["STIPEND_BUDGET"],
    }
    defaults.update(overrides)
    return defaults


def create_school_target_payload(**overrides) -> dict:
    defaults = {
        "school_name": DEFAULTS["SCHOOL_NAME"],
        "tier": DEFAULTS["TIER"],
        "application_cap": DEFAULTS["APPLICATION_CAP"],
        "stipend_region": DEFAULTS["STIPEND_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_campus_event_payload(**overrides) -> dict:
    defaults = {
        "school_target_id": None,
        "event_type": DEFAULTS["EVENT_TYPE"],
        "start_at": "2026-05-12T10:00:00Z",
        "end_at": "2026-05-12T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    defaults = {
        "email": "a@x.com",
        "full_name": "Candidate A",
        "expected_graduation_date": DEFAULTS["GRAD_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "candidate_id": None,
        "school_target_id": None,
        "relocation_distance_miles": DEFAULTS["RELOCATION_MILES"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Eve",
        "email": "ev@co.com",
    }
    defaults.update(overrides)
    return defaults


def create_interview_day_payload(**overrides) -> dict:
    defaults = {
        "window_start_at": DEFAULTS["DAY_START"],
        "window_end_at": DEFAULTS["DAY_END"],
        "capacity": DEFAULTS["DAY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_interview_slot_payload(**overrides) -> dict:
    defaults = {
        "application_id": None,
        "evaluator_id": None,
        "start_at": DEFAULTS["SLOT_START"],
        "end_at": DEFAULTS["SLOT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(**overrides) -> dict:
    defaults = {
        "score": 4,
        "recommendation": "HIRE",
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "weekly_rate_cents": DEFAULTS["WEEKLY_RATE"],
        "duration_weeks": DEFAULTS["DURATION_WEEKS"],
    }
    defaults.update(overrides)
    return defaults


def create_intern_project_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PROJECT_TITLE"],
        "capacity": DEFAULTS["PROJECT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_project_assignment_payload(**overrides) -> dict:
    defaults = {
        "application_id": None,
        "mentor_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_intern_evaluation_payload(**overrides) -> dict:
    defaults = {
        "eval_type": "MID",
        "rating": 4,
        "would_rehire": True,
    }
    defaults.update(overrides)
    return defaults
