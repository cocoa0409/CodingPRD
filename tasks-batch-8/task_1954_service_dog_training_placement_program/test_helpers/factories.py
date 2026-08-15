"""Payload factories — one per creatable entity, input fields only (PRD §3)."""

_counter = {"n": 0}


def _unique(tag: str) -> str:
    _counter["n"] += 1
    return f"{tag}-{_counter['n']:04d}"


def create_applicant_payload(**overrides) -> dict:
    n = _unique("applicant")
    defaults = {
        "full_name": f"Applicant {n}",
        "email": f"{n}@example.org",
        "placement_track": "MOBILITY",
        "household_income_cents": 12_000_000,
        "region": "NW",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "required_tasks": ["RETRIEVE_ITEMS"],
        "task_urgency_tier": "STANDARD",
        "home_environment_score": 6,
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(**overrides) -> dict:
    n = _unique("donor")
    defaults = {"donor_name": f"Donor {n}", "amount_cents": 100_000}
    defaults.update(overrides)
    return defaults


def create_puppy_raiser_payload(**overrides) -> dict:
    n = _unique("raiser")
    defaults = {
        "full_name": f"Raiser {n}",
        "region": "NW",
        "foster_capacity": 1,
        "experience_score": 50,
    }
    defaults.update(overrides)
    return defaults


def create_trainer_payload(**overrides) -> dict:
    n = _unique("trainer")
    defaults = {"full_name": f"Trainer {n}", "pat_certified": False}
    defaults.update(overrides)
    return defaults


def create_dog_payload(**overrides) -> dict:
    n = _unique("dog")
    defaults = {
        "name": f"Dog {n}",
        "origin": "DONATED",
        "breed": "Labrador",
        "sex": "MALE",
        "born_on": "2024-01-01",
        "region": "NW",
        "donor_name": f"Donor {n}",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    defaults = {
        "hip_grade": "GOOD",
        "elbow_grade": "NORMAL",
        "eye_result": "CLEAR",
        "cardiac_result": "NORMAL",
        "genetic_panel": "CARRIER",
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    defaults = {"category": "OBEDIENCE", "score": 80}
    defaults.update(overrides)
    return defaults


def create_class_payload(**overrides) -> dict:
    n = _unique("class")
    defaults = {
        "name": f"Class {n}",
        "starts_on": "2026-09-01",
        "ends_on": "2026-10-15",
        "capacity": 2,
        "total_sessions": 20,
    }
    defaults.update(overrides)
    return defaults


def create_pat_payload(**overrides) -> dict:
    defaults = {"scheduled_at": "2026-10-10T10:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_followup_payload(**overrides) -> dict:
    defaults = {"due_on": "2027-02-14"}
    defaults.update(overrides)
    return defaults


def create_recertification_payload(**overrides) -> dict:
    defaults = {"scheduled_on": "2027-10-20"}
    defaults.update(overrides)
    return defaults


def create_support_request_payload(**overrides) -> dict:
    defaults = {
        "category": "EQUIPMENT",
        "description": "support request description",
    }
    defaults.update(overrides)
    return defaults
