"""Payload factories — one per entity, input fields only.

Field names are PRD-exact (PRD §3). Only `source: input` fields appear here.
"""


def create_owner_payload(**overrides) -> dict:
    """Owner input: full_name, email, phone (PRD §3.1)."""
    defaults = {
        "full_name": "Test Owner",
        "email": "owner@example.com",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_dog_payload(owner_id: str, **overrides) -> dict:
    """Dog input: owner_id, name, breed, birth_date (PRD §3.1)."""
    defaults = {
        "owner_id": owner_id,
        "name": "Rex",
        "breed": "Labrador",
        "birth_date": "2024-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_vaccination_payload(vaccine_type: str, **overrides) -> dict:
    """Vaccination input: vaccine_type, administered_on, expires_on (PRD §3.2)."""
    defaults = {
        "vaccine_type": vaccine_type,
        "administered_on": "2026-01-01",
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_behavioral_intake_payload(**overrides) -> dict:
    """Behavioral intake input: reactivity_score, bite_history, recommended_level (PRD §3.1).

    bite_history defaults to false per PRD; here we set a low, non-flagging score.
    """
    defaults = {
        "reactivity_score": 2,
        "bite_history": False,
        "recommended_level": "BASIC",
    }
    defaults.update(overrides)
    return defaults


def create_trainer_payload(**overrides) -> dict:
    """Trainer input: full_name, certified_levels, optional handles_private (PRD §3.3)."""
    defaults = {
        "full_name": "Test Trainer",
        "certified_levels": ["BASIC"],
    }
    defaults.update(overrides)
    return defaults


def create_class_series_payload(**overrides) -> dict:
    """ClassSeries input: title, level, optional prerequisite_level, modality, capacity,
    session_count, list_price_cents, credit_cost (PRD §3.3)."""
    defaults = {
        "title": "Basic Obedience",
        "level": "BASIC",
        "modality": "GROUP",
        "capacity": 5,
        "session_count": 1,
        "list_price_cents": 12000,
        "credit_cost": 2,
    }
    defaults.update(overrides)
    return defaults


def create_class_session_payload(series_id: str, trainer_id: str, **overrides) -> dict:
    """ClassSession input: series_id, trainer_id, sequence_index, starts_at, ends_at,
    optional is_makeup_slot (PRD §3.3)."""
    defaults = {
        "series_id": series_id,
        "trainer_id": trainer_id,
        "sequence_index": 1,
        "starts_at": "2026-07-01T09:00:00Z",
        "ends_at": "2026-07-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(dog_id: str, series_id: str, expected_series_version: int,
                              **overrides) -> dict:
    """Enrollment input: dog_id, series_id, payment_method, optional package_id,
    mandatory expected_series_version (PRD §3.6, §2.6)."""
    defaults = {
        "dog_id": dog_id,
        "series_id": series_id,
        "payment_method": "CASH",
        "expected_series_version": expected_series_version,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(owner_id: str, tier: str = "STARTER", **overrides) -> dict:
    """Package input: owner_id, tier (PRD §3.12)."""
    defaults = {
        "owner_id": owner_id,
        "tier": tier,
    }
    defaults.update(overrides)
    return defaults


def create_makeup_booking_payload(attendance_id: str, makeup_session_id: str, **overrides) -> dict:
    """MakeupBooking input: attendance_id, makeup_session_id (PRD §3.11)."""
    defaults = {
        "attendance_id": attendance_id,
        "makeup_session_id": makeup_session_id,
    }
    defaults.update(overrides)
    return defaults


def mark_attendance_payload(attendance_id: str, state: str = "PRESENT", **overrides) -> dict:
    """Attendance mark input: attendance_id, state (PRD §3.8)."""
    defaults = {
        "attendance_id": attendance_id,
        "state": state,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    """Clock input: to_iso8601 (PRD §2.10)."""
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
