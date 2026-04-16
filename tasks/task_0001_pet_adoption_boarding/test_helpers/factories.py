"""Payload factories from scaffold Table 1 input fields."""
from datetime import datetime, timezone, timedelta


def _iso(dt: datetime) -> str:
    """Format as ISO 8601 UTC with millisecond precision (Z suffix)."""
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return s


def future_iso(days: int = 1) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(days=days))


def past_iso(days: int = 1) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


def now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


# --- Factories ---

def create_shelter_payload(**overrides) -> dict:
    defaults = {
        "name": "Happy Tails Shelter",
        "boarding_capacity": 10,
        "adoption_fee_base": 20000,          # cents
        "boarding_rate_per_night": 5000,     # cents
    }
    defaults.update(overrides)
    return defaults


def create_animal_payload(**overrides) -> dict:
    defaults = {
        "name": "Biscuit",
        "species": "DOG",
        "age_months": 24,
    }
    defaults.update(overrides)
    return defaults


def create_vaccination_payload(**overrides) -> dict:
    """Default: RABIES, administered now, expires far in future."""
    defaults = {
        "vaccine_type": "RABIES",
        "administered_date": past_iso(1),
        "expires_date": future_iso(365),
        "lot_number": "LOT-A-0001",
    }
    defaults.update(overrides)
    return defaults


def create_adopter_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Alice Adopter",
        "household_size": 2,
        "has_yard": True,
    }
    defaults.update(overrides)
    return defaults


def create_home_visit_payload(**overrides) -> dict:
    defaults = {
        "scheduled_for": future_iso(3),
        "inspector_id": "inspector-default",
    }
    defaults.update(overrides)
    return defaults


def submit_home_visit_payload(**overrides) -> dict:
    defaults = {
        "safety_score": 85,
        "yard_verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(adopter_id: str, animal_id: str, **overrides) -> dict:
    defaults = {
        "adopter_id": adopter_id,
        "animal_id": animal_id,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(animal_id: str, owner_id: str, nights: int = 3, **overrides) -> dict:
    """Reservation starts tomorrow for `nights` nights by default."""
    check_in = datetime.now(timezone.utc) + timedelta(days=1)
    check_out = check_in + timedelta(days=nights)
    defaults = {
        "animal_id": animal_id,
        "owner_id": owner_id,
        "check_in_date": _iso(check_in),
        "check_out_date": _iso(check_out),
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(subject_type: str, subject_id: str, amount: int,
                              method: str = "CARD", **overrides) -> dict:
    defaults = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "amount": amount,
        "method": method,
    }
    defaults.update(overrides)
    return defaults
