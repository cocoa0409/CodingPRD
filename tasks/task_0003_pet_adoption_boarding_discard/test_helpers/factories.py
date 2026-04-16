"""Payload factories from scaffold Table 1 input fields."""
from datetime import datetime, timedelta, timezone


def _future_iso(days=365):
    """Return an ISO 8601 timestamp `days` in the future."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _past_iso(days=30):
    """Return an ISO 8601 timestamp `days` in the past."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _future_date_iso(days=7):
    """Return an ISO 8601 timestamp `days` in the future (for scheduling)."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


# ---------------------------------------------------------------------------
# Shelter
# ---------------------------------------------------------------------------

def create_shelter_payload(**overrides) -> dict:
    defaults = {
        "name": "Happy Paws Shelter",
        "address": "123 Shelter Lane, Springfield, IL 62704",
        "boarding_capacity": 20,
        "tax_rate": 0.08,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Animal
# ---------------------------------------------------------------------------

def create_animal_payload(shelter_id: str, **overrides) -> dict:
    defaults = {
        "shelter_id": shelter_id,
        "name": "Buddy",
        "species": "DOG",
        "breed": "Golden Retriever",
        "age_months": 24,
        "weight_kg": 30.0,
        "temperament": "CALM",
        "special_needs": [],
    }
    defaults.update(overrides)
    return defaults


def create_cat_payload(shelter_id: str, **overrides) -> dict:
    base = {
        "shelter_id": shelter_id,
        "name": "Whiskers",
        "species": "CAT",
        "breed": "Persian",
        "age_months": 36,
        "weight_kg": 4.5,
        "temperament": "CALM",
        "special_needs": [],
    }
    base.update(overrides)
    return base


def create_rabbit_payload(shelter_id: str, **overrides) -> dict:
    base = {
        "shelter_id": shelter_id,
        "name": "Thumper",
        "species": "RABBIT",
        "breed": "Holland Lop",
        "age_months": 12,
        "weight_kg": 2.0,
        "temperament": "CALM",
        "special_needs": [],
    }
    base.update(overrides)
    return base


def create_bird_payload(shelter_id: str, **overrides) -> dict:
    base = {
        "shelter_id": shelter_id,
        "name": "Tweety",
        "species": "BIRD",
        "breed": "Parakeet",
        "age_months": 6,
        "weight_kg": 0.03,
        "temperament": "MODERATE",
        "special_needs": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# VaccinationRecord
# ---------------------------------------------------------------------------

def create_vaccination_record_payload(animal_id: str, **overrides) -> dict:
    defaults = {
        "animal_id": animal_id,
        "vaccine_name": "RABIES",
        "administered_date": _past_iso(days=30),
        "expiry_date": _future_iso(days=365),
        "batch_number": "BATCH-001",
        "veterinarian_name": "Dr. Smith",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Adopter
# ---------------------------------------------------------------------------

def create_adopter_payload(shelter_id: str, **overrides) -> dict:
    defaults = {
        "shelter_id": shelter_id,
        "full_name": "Jane Doe",
        "email": "jane.doe@example.com",
        "phone": "+1-555-0101",
        "home_type": "HOUSE",
        "has_yard": True,
        "has_other_pets": False,
        "other_pet_species": [],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AdoptionApplication
# ---------------------------------------------------------------------------

def create_adoption_application_payload(animal_id: str, adopter_id: str, **overrides) -> dict:
    defaults = {
        "animal_id": animal_id,
        "adopter_id": adopter_id,
        "reason": "I have always wanted a companion animal and have a suitable home.",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# HomeVisit
# ---------------------------------------------------------------------------

def create_home_visit_payload(adopter_id: str, application_id: str, **overrides) -> dict:
    defaults = {
        "adopter_id": adopter_id,
        "application_id": application_id,
        "scheduled_date": _future_date_iso(days=7),
    }
    defaults.update(overrides)
    return defaults


def create_home_visit_assessment_payload(**overrides) -> dict:
    """Assessment fields for completing a home visit (all pass)."""
    defaults = {
        "yard_adequate": True,
        "space_adequate": True,
        "safety_hazards_found": False,
        "existing_pets_compatible": True,
        "notes": "Home meets all requirements. Clean and spacious.",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# BoardingReservation
# ---------------------------------------------------------------------------

def create_boarding_reservation_payload(
    shelter_id: str, animal_id: str, **overrides
) -> dict:
    defaults = {
        "shelter_id": shelter_id,
        "animal_id": animal_id,
        "owner_name": "John Owner",
        "owner_contact": "+1-555-0202",
        "check_in_date": _future_date_iso(days=3),
        "check_out_date": _future_date_iso(days=10),
        "special_instructions": "Needs daily medication at 8am.",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ComplianceHold
# ---------------------------------------------------------------------------

def create_compliance_hold_payload(animal_id: str, **overrides) -> dict:
    defaults = {
        "animal_id": animal_id,
        "hold_type": "HEALTH_CONCERN",
        "reason": "Animal showing signs of respiratory infection.",
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# FeeSchedule
# ---------------------------------------------------------------------------

def create_fee_schedule_payload(shelter_id: str, **overrides) -> dict:
    defaults = {
        "shelter_id": shelter_id,
        "fee_type": "ADOPTION_BASE",
        "species": "DOG",
        "amount": 150.00,
        "effective_from": _past_iso(days=365),
        "effective_to": _future_iso(days=365),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# FeeInvoice payment
# ---------------------------------------------------------------------------

def create_payment_payload(amount: float, **overrides) -> dict:
    defaults = {
        "amount": amount,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ComplianceHold resolution
# ---------------------------------------------------------------------------

def create_resolve_hold_payload(**overrides) -> dict:
    defaults = {
        "resolution_notes": "Issue has been addressed and animal cleared by vet.",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Rejection
# ---------------------------------------------------------------------------

def create_rejection_payload(**overrides) -> dict:
    defaults = {
        "rejection_reason": "Adopter does not meet the housing requirements for this animal.",
    }
    defaults.update(overrides)
    return defaults
