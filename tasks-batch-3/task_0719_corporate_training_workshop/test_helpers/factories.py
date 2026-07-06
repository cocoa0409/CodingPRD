"""Payload factories — one per entity, input fields only."""


def create_program_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Program",
        "category": "TECHNICAL",
        "delivery_mode": "VIRTUAL",
    }
    defaults.update(overrides)
    return defaults


def create_program_version_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "version_label": "v1",
        "duration_hours": 4,
        "pricing_model": "PER_SEAT",
        "per_seat_cents": 10000,
        "min_seats": 1,
    }
    defaults.update(overrides)
    return defaults


def create_facilitator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Facilitator",
        "email": "facilitator@example.com",
        "certified_categories": ["TECHNICAL"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "client_name": "Test Client",
        "budget_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(program_version_id: str, lead_facilitator_id: str, **overrides) -> dict:
    defaults = {
        "program_version_id": program_version_id,
        "lead_facilitator_id": lead_facilitator_id,
        "seat_capacity": 5,
        "delivery_mode": "VIRTUAL",
        "starts_at": "2026-04-01T09:00:00Z",
        "ends_at": "2026-04-01T17:00:00Z",
        "enroll_deadline": "2026-03-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Session",
        "starts_at": "2026-04-01T09:00:00Z",
        "ends_at": "2026-04-01T10:00:00Z",
        "room_or_url": "ROOM-A",
    }
    defaults.update(overrides)
    return defaults


def create_session_assignment_payload(facilitator_id: str, **overrides) -> dict:
    defaults = {"facilitator_id": facilitator_id}
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    defaults = {
        "learner_email": "learner@example.com",
        "learner_name": "Test Learner",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {"raw_score": 9, "max_score": 10}
    defaults.update(overrides)
    return defaults


def create_certificate_payload(assessment_id: str, **overrides) -> dict:
    defaults = {"assessment_id": assessment_id}
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(**overrides) -> dict:
    defaults = {"nps_rating": 9}
    defaults.update(overrides)
    return defaults
