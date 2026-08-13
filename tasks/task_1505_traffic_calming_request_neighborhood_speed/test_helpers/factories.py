"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_segment_payload(**overrides) -> dict:
    """PRD §3.1 input fields: name, speed_limit_mph, household_count,
    functional_class; optional emergency_route / crash_count_3yr /
    pedestrian_generator_count."""
    defaults = {
        "name": "Maple Ave between 3rd and 5th",
        "speed_limit_mph": 30,
        "household_count": 4,
        "functional_class": "LOCAL",
        "emergency_route": False,
        "crash_count_3yr": 0,
        "pedestrian_generator_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    """PRD §3.1 input fields: full_name, email, street_segment_id, household_ref."""
    defaults = {
        "full_name": "Robin Rivera",
        "email": "robin.rivera@example.com",
        "street_segment_id": None,
        "household_ref": "H1",
    }
    defaults.update(overrides)
    return defaults


def create_request_payload(**overrides) -> dict:
    """PRD §3.2 input fields: street_segment_id, title, requested_budget_cents."""
    defaults = {
        "street_segment_id": None,
        "title": "Calm our street",
        "requested_budget_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_speed_study_payload(**overrides) -> dict:
    """PRD §3.3 input fields: study_type, window_start_date, window_end_date."""
    defaults = {
        "study_type": "INITIAL",
        "window_start_date": "2026-08-03",
        "window_end_date": "2026-08-05",
    }
    defaults.update(overrides)
    return defaults


def create_observation_payload(**overrides) -> dict:
    """PRD §3.3 input fields: observation_date, vehicle_count, p85_speed_mph,
    mean_speed_mph; optional is_valid (defaults to true)."""
    defaults = {
        "observation_date": "2026-08-03",
        "vehicle_count": 3000,
        "p85_speed_mph": 40.0,
        "mean_speed_mph": 33.0,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(**overrides) -> dict:
    """PRD §3.5 input fields: treatment_type, estimated_cost_cents,
    expected_request_version."""
    defaults = {
        "treatment_type": "SPEED_HUMP",
        "estimated_cost_cents": 9000,
        "expected_request_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_funding_cycle_payload(**overrides) -> dict:
    """PRD §3.4 input fields: cycle_year, budget_total_cents."""
    defaults = {
        "cycle_year": 2026,
        "budget_total_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_ballot_payload(**overrides) -> dict:
    """PRD §3.6 input field: close_date."""
    defaults = {
        "close_date": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(**overrides) -> dict:
    """PRD §3.6 input field: choice."""
    defaults = {
        "choice": "FOR",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    """PRD §3.7 input field: crew_ref."""
    defaults = {
        "crew_ref": "CREW-1",
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(**overrides) -> dict:
    """PRD §3.7 input fields: scheduled_date, duration_days."""
    defaults = {
        "scheduled_date": "2026-08-15",
        "duration_days": 1,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    """PRD §3.7 input field: decision."""
    defaults = {
        "decision": "CLEARED",
    }
    defaults.update(overrides)
    return defaults


def create_removal_request_payload(**overrides) -> dict:
    """PRD §3.8 input field: reason."""
    defaults = {
        "reason": "Residents want it gone",
    }
    defaults.update(overrides)
    return defaults
