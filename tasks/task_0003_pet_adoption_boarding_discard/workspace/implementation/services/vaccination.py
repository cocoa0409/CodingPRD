"""Vaccination compliance logic."""

from datetime import datetime, timezone
import db

SPECIES_VACCINE_MAP = {
    "DOG": ["RABIES", "DHPP", "BORDETELLA"],
    "CAT": ["RABIES", "FVRCP"],
    "RABBIT": ["RHDV"],
    "BIRD": [],
    "OTHER": [],
}

# Boarding requires BORDETELLA for all except BIRD
BOARDING_EXTRA = {
    "DOG": [],  # already in default
    "CAT": ["BORDETELLA"],
    "RABBIT": ["BORDETELLA"],
    "BIRD": [],
    "OTHER": ["BORDETELLA"],
}


def check_vaccination_compliant(animal_id, for_boarding=False):
    """Return True if all required vaccinations are up-to-date."""
    animal = db.animals.get(animal_id)
    if not animal:
        return False
    species = animal["species"]
    required = list(SPECIES_VACCINE_MAP.get(species, []))
    if for_boarding:
        required = list(set(required + BOARDING_EXTRA.get(species, [])))

    now = datetime.now(timezone.utc)
    for vaccine in required:
        records = [
            r for r in db.vaccination_records.values()
            if r["animal_id"] == animal_id and r["vaccine_name"] == vaccine
        ]
        valid = [r for r in records if _parse_dt(r["expiry_date"]) > now]
        if len(valid) == 0:
            return False
    return True


def update_animal_vaccination_compliant(animal_id):
    """Recompute and store vaccination_compliant on the animal."""
    animal = db.animals.get(animal_id)
    if not animal:
        return
    animal["vaccination_compliant"] = check_vaccination_compliant(animal_id)


def _parse_dt(s):
    """Parse ISO 8601 datetime string."""
    if isinstance(s, datetime):
        return s
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def is_vaccination_record_valid(record):
    """Check if a single vaccination record is valid (not expired)."""
    now = datetime.now(timezone.utc)
    return _parse_dt(record["expiry_date"]) > now
