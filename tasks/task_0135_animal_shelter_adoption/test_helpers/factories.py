"""Payload factories — one per entity, input fields only."""


def create_shelter_payload(**overrides) -> dict:
    """POST /shelters input. Only `name` is required; the rest have server defaults."""
    defaults = {"name": "Test Shelter"}
    defaults.update(overrides)
    return defaults


def create_kennel_payload(**overrides) -> dict:
    """POST /kennels input. `label` required; `capacity` optional (default 1)."""
    defaults = {"label": "A-1"}
    defaults.update(overrides)
    return defaults


def create_animal_payload(**overrides) -> dict:
    """POST /animals input. name, species, age_months all required."""
    defaults = {"name": "Buddy", "species": "DOG", "age_months": 36}
    defaults.update(overrides)
    return defaults


def create_intake_record_payload(animal_id, source="SURRENDER", **overrides) -> dict:
    """POST /intake-records input. surrendering_party required for SURRENDER/TRANSFER."""
    defaults = {"animal_id": animal_id, "source": source}
    if source in ("SURRENDER", "TRANSFER"):
        defaults["surrendering_party"] = "Prior Owner"
    defaults.update(overrides)
    return defaults


def create_kennel_assignment_payload(kennel_id, animal_id, expected_kennel_version, **overrides) -> dict:
    """POST /kennel-assignments input. expected_kennel_version mandatory (OCC)."""
    defaults = {
        "kennel_id": kennel_id,
        "animal_id": animal_id,
        "expected_kennel_version": expected_kennel_version,
    }
    defaults.update(overrides)
    return defaults


def create_medical_record_payload(animal_id, record_type="EXAM", outcome="CLEAR", **overrides) -> dict:
    """POST /medical-records input."""
    defaults = {"animal_id": animal_id, "record_type": record_type}
    if outcome is not None:
        defaults["outcome"] = outcome
    defaults.update(overrides)
    return defaults


def create_microchip_payload(animal_id, chip_number, **overrides) -> dict:
    """POST /microchips input. chip_number globally unique."""
    defaults = {"animal_id": animal_id, "chip_number": chip_number}
    defaults.update(overrides)
    return defaults


def create_owner_claim_payload(animal_id, claimant_name="Claimant", **overrides) -> dict:
    """POST /owner-claims input."""
    defaults = {"animal_id": animal_id, "claimant_name": claimant_name}
    defaults.update(overrides)
    return defaults


def create_adopter_account_payload(email="adopter@example.com", **overrides) -> dict:
    """POST /adopter-accounts input. email globally unique."""
    defaults = {"full_name": "Adopter Person", "email": email}
    defaults.update(overrides)
    return defaults


def create_adoption_application_payload(animal_id, adopter_id, **overrides) -> dict:
    """POST /adoption-applications input."""
    defaults = {"animal_id": animal_id, "adopter_id": adopter_id}
    defaults.update(overrides)
    return defaults


def create_foster_home_payload(**overrides) -> dict:
    """POST /foster-homes input. contact_name required; rest optional."""
    defaults = {"contact_name": "Foster Family"}
    defaults.update(overrides)
    return defaults


def create_foster_placement_payload(foster_home_id, animal_id, **overrides) -> dict:
    """POST /foster-placements input."""
    defaults = {"foster_home_id": foster_home_id, "animal_id": animal_id}
    defaults.update(overrides)
    return defaults


def create_euthanasia_decision_payload(animal_id, reason="MEDICAL_UNTREATABLE", **overrides) -> dict:
    """POST /euthanasia-decisions input."""
    defaults = {"animal_id": animal_id, "reason": reason}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    """POST /_clock/set input."""
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
