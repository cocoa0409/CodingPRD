"""Payload factories — one per entity, input fields only."""


def create_camp_payload(**overrides) -> dict:
    """POST /camps. Only `name` is required; config knobs are optional."""
    defaults = {"name": "Test Camp"}
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    """POST /camps/{id}/sessions."""
    defaults = {
        "name": "Session A",
        "starts_on": "2026-07-01T00:00:00Z",
        "ends_on": "2026-07-14T00:00:00Z",
        "visiting_day_on": "2026-07-07T00:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_cabin_payload(**overrides) -> dict:
    """POST /sessions/{id}/cabins."""
    defaults = {
        "name": "Birch",
        "gender_band": "BOYS",
        "min_age": 8,
        "max_age": 12,
        "bunk_capacity": 6,
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    """POST /camps/{id}/staff."""
    defaults = {
        "full_name": "Counselor A",
        "role_kind": "COUNSELOR",
        "is_background_cleared": True,
    }
    defaults.update(overrides)
    return defaults


def create_cabin_assignment_payload(cabin_id: str, staff_member_id: str, **overrides) -> dict:
    """POST /cabin-assignments."""
    defaults = {"cabin_id": cabin_id, "staff_member_id": staff_member_id}
    defaults.update(overrides)
    return defaults


def register_guardian_payload(**overrides) -> dict:
    """POST /guardians/register."""
    defaults = {
        "email": "guardian@example.com",
        "full_name": "Test Guardian",
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_camper_payload(**overrides) -> dict:
    """POST /campers."""
    defaults = {"full_name": "Test Camper", "age": 10, "gender": "BOY"}
    defaults.update(overrides)
    return defaults


def create_health_form_payload(camper_id: str, **overrides) -> dict:
    """POST /health-forms. Only camper_id is required; medical fields optional."""
    defaults = {"camper_id": camper_id}
    defaults.update(overrides)
    return defaults


def create_application_payload(camper_id: str, session_id: str, **overrides) -> dict:
    """POST /applications."""
    defaults = {"camper_id": camper_id, "session_id": session_id}
    defaults.update(overrides)
    return defaults


def create_financial_aid_payload(application_id: str, amount_cents: int,
                                 kind: str = "NEED_GRANT", **overrides) -> dict:
    """POST /financial-aid."""
    defaults = {"application_id": application_id, "kind": kind, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_activity_payload(**overrides) -> dict:
    """POST /sessions/{id}/activities."""
    defaults = {
        "name": "Archery",
        "slot_day": 1,
        "starts_minute": 540,
        "ends_minute": 600,
        "seat_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_activity_enrollment_payload(offering_id: str, application_id: str, **overrides) -> dict:
    """POST /activity-enrollments."""
    defaults = {"offering_id": offering_id, "application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_canteen_account_payload(application_id: str, **overrides) -> dict:
    """POST /canteen-accounts."""
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_canteen_transaction_payload(kind: str, amount_cents: int, **overrides) -> dict:
    """POST /canteen-accounts/{id}/transactions."""
    defaults = {"kind": kind, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
