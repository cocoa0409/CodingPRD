"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_owner_payload(**overrides) -> dict:
    """POST /owners input: full_name, email, address_zip (PRD §3.1)."""
    defaults = {
        "full_name": "Test Owner",
        "email": "owner@example.com",
        "address_zip": "10001",
    }
    defaults.update(overrides)
    return defaults


def create_pet_payload(owner_id: str, **overrides) -> dict:
    """POST /pets input: owner_id, name, species, breed, is_altered, birth_date.

    is_altered defaults to false per PRD §3.1; is_dangerous/status are computed.
    """
    defaults = {
        "owner_id": owner_id,
        "name": "Test Pet",
        "species": "DOG",
        "breed": "Mixed",
        "is_altered": False,
        "birth_date": "2023-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_vaccination_record_payload(pet_id: str, **overrides) -> dict:
    """POST /vaccination-records input: pet_id, vaccine_type, administered_on,
    expires_on, vet_license_no (PRD §3.1)."""
    defaults = {
        "pet_id": pet_id,
        "vaccine_type": "RABIES",
        "administered_on": "2025-06-01T00:00:00Z",
        "expires_on": "2030-06-01T00:00:00Z",
        "vet_license_no": "VET-0001",
    }
    defaults.update(overrides)
    return defaults


def create_kennel_payload(owner_id: str, **overrides) -> dict:
    """POST /kennels input: owner_id, facility_name, slot_capacity (PRD §3.2)."""
    defaults = {
        "owner_id": owner_id,
        "facility_name": "Test Kennel",
        "slot_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(owner_id: str, pet_id: str, **overrides) -> dict:
    """POST /licenses input: owner_id, pet_id, license_kind, term_years, kennel_id?.

    INDIVIDUAL leaves kennel_id null; KENNEL supplies it (PRD §3.2).
    """
    defaults = {
        "owner_id": owner_id,
        "pet_id": pet_id,
        "license_kind": "INDIVIDUAL",
        "term_years": 1,
    }
    defaults.update(overrides)
    return defaults


def create_dangerous_dog_case_payload(pet_id: str, **overrides) -> dict:
    """POST /dangerous-dog-cases input: pet_id, incident_summary, severity (§3.7)."""
    defaults = {
        "pet_id": pet_id,
        "incident_summary": "Incident report",
        "severity": "BITE",
    }
    defaults.update(overrides)
    return defaults


def create_lost_found_report_payload(report_type: str, species: str, **overrides) -> dict:
    """POST /lost-found-reports input: report_type, species, zip_seen, reported_at,
    pet_id?, tag_serial_seen? (PRD §3.8)."""
    defaults = {
        "report_type": report_type,
        "species": species,
        "zip_seen": "30303",
        "reported_at": "2026-03-01T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults
