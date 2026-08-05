"""Payload factories — one per entity, input fields only."""


def create_employer_program_payload(**overrides) -> dict:
    payload = {
        "name": "Acme Wellness",
        "budget_total_cents": 100000,
        "nrt_courses_allotted": 3,
    }
    payload.update(overrides)
    return payload


def create_coach_payload(**overrides) -> dict:
    payload = {
        "full_name": "Coach EN",
        "languages": ["EN"],
    }
    payload.update(overrides)
    return payload


def create_participant_payload(**overrides) -> dict:
    payload = {
        "full_name": "Pat Participant",
        "email": "pat@example.com",
        "primary_language": "EN",
        "cigarettes_per_day": 10,
    }
    payload.update(overrides)
    return payload


def create_readiness_assessment_payload(**overrides) -> dict:
    payload = {
        "motivation_score": 6,
        "confidence_score": 6,
        "prior_quit_attempts": 0,
    }
    payload.update(overrides)
    return payload


def create_quit_attempt_payload(**overrides) -> dict:
    payload = {
        "quit_date": "2026-06-02T00:00:00Z",
        "method": "COLD_TURKEY",
    }
    payload.update(overrides)
    return payload


def create_coaching_call_payload(**overrides) -> dict:
    payload = {
        "scheduled_start": "2026-06-02T10:00:00Z",
        "duration_minutes": 30,
    }
    payload.update(overrides)
    return payload


def create_nrt_shipment_payload(**overrides) -> dict:
    payload = {
        "medication_type": "PATCH",
        "course_start_date": "2026-06-05T00:00:00Z",
        "course_end_date": "2026-06-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_incentive_award_payload(**overrides) -> dict:
    payload = {
        "milestone_type": "DISCRETIONARY",
        "amount_cents": 500,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(**overrides) -> dict:
    payload = {
        "referral_type": "PROVIDER",
        "target_name": "Dr Lung",
    }
    payload.update(overrides)
    return payload


def create_follow_up_outcome_payload(**overrides) -> dict:
    payload = {
        "day": 7,
        "abstinent": True,
    }
    payload.update(overrides)
    return payload
