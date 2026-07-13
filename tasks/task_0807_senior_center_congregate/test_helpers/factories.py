"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_participant_payload(**overrides) -> dict:
    """Participant registration payload (PRD 3.1). disability_count is optional
    and defaults to 0 server-side when omitted."""
    defaults = {
        "full_name": _unique("Participant"),
        "birth_date": "1948-01-15T00:00:00Z",
        "gender": "FEMALE",
        "ethnicity": "NON_HISPANIC",
        "race": "WHITE",
        "poverty_status": "AT_OR_ABOVE",
        "lives_alone": True,
        "rural": False,
        "veteran": False,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(**overrides) -> dict:
    """GrantAward create payload (PRD 3.2)."""
    defaults = {
        "title": _unique("Grant"),
        "oaa_title": "IIID",
        "category": "WELLNESS",
        "authorized_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    """Donation create payload (PRD 3.2)."""
    defaults = {
        "donor_name": _unique("Donor"),
        "category": "WELLNESS",
        "amount_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_funded_service_payload(**overrides) -> dict:
    """FundedService create payload (PRD 3.3). participant_id, category,
    grant_award_id, and expected_grant_award_version must be supplied by the
    caller. donation_id is optional (omitted when no donation is drawn)."""
    defaults = {
        "quantity": 1,
        "service_date": "2026-03-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    """Room create payload (PRD 3.4)."""
    defaults = {
        "name": _unique("Room"),
        "capacity": 20,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    """ActivitySession create payload (PRD 3.4). category is optional and
    defaults to ACTIVITY server-side when omitted. room_id must be supplied."""
    defaults = {
        "title": _unique("Session"),
        "starts_at": "2026-03-10T10:00:00Z",
        "ends_at": "2026-03-10T11:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_signup_payload(**overrides) -> dict:
    """ActivitySignup create payload (PRD 3.4). session_id and participant_id
    must be supplied by the caller."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    """Vehicle create payload (PRD 3.5)."""
    defaults = {
        "name": _unique("Vehicle"),
        "seat_capacity": 8,
    }
    defaults.update(overrides)
    return defaults


def create_transport_payload(**overrides) -> dict:
    """TransportationRequest create payload (PRD 3.5). participant_id,
    vehicle_id, and linked_session_id must be supplied by the caller."""
    defaults = {
        "starts_at": "2026-03-10T09:00:00Z",
        "ends_at": "2026-03-10T09:45:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_meal_day_payload(**overrides) -> dict:
    """MealServiceDay create payload (PRD 3.6)."""
    defaults = {
        "service_date": "2026-03-10T12:00:00Z",
        "site_name": "Main Hall",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    """MealReservation create payload (PRD 3.6). service_day_id, participant_id,
    and expected_service_day_version must be supplied by the caller.
    suggested_contribution_cents is optional and defaults to 0 server-side."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    """WellnessProgram create payload (PRD 3.7)."""
    defaults = {
        "title": _unique("Program"),
        "model": "ENHANCE_FITNESS",
        "total_sessions": 6,
        "fidelity_min_sessions": 5,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    """WellnessEnrollment create payload (PRD 3.7). program_id and
    participant_id must be supplied by the caller."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_volunteer_shift_payload(**overrides) -> dict:
    """VolunteerShift create payload (PRD 3.8)."""
    defaults = {
        "volunteer_name": _unique("Volunteer"),
        "role": "meal-server",
        "hours": 3.0,
        "service_date": "2026-03-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
