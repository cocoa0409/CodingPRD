"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _unique_email(tag: str = "user") -> str:
    return f"{tag}-{uuid.uuid4().hex[:12]}@example.org"


def _unique_policy_number() -> str:
    return f"POL-{uuid.uuid4().hex[:12].upper()}"


def create_handler_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Handler",
        "email": _unique_email("handler"),
        "region_code": "WA",
        "volunteer_since": "2024-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_animal_payload(**overrides) -> dict:
    defaults = {
        "name": "Rex",
        "species": "DOG",
        "breed": "Beagle",
        "date_of_birth": "2021-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(animal_id, team_name="Team One", **overrides) -> dict:
    payload = {"animal_id": animal_id, "team_name": team_name}
    payload.update(overrides)
    return payload


def create_evaluator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Evaluator",
        "email": _unique_email("evaluator"),
        "region_code": "WA",
        "specializations": ["DOG"],
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(team_id, **overrides) -> dict:
    payload = {"team_id": team_id}
    payload.update(overrides)
    return payload


def create_certification_payload(team_id, evaluation_id, **overrides) -> dict:
    payload = {"team_id": team_id, "evaluation_id": evaluation_id}
    payload.update(overrides)
    return payload


def create_vaccination_record_payload(animal_id, **overrides) -> dict:
    defaults = {
        "animal_id": animal_id,
        "vaccine_type": "RABIES",
        "administered_on": "2026-07-01",
        "valid_until": "2029-12-31",
        "veterinarian_name": "Dr V",
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Facility",
        "facility_type": "SCHOOL",
        "region_code": "WA",
        "max_visit_minutes": 60,
        "allowed_species": ["DOG"],
        "min_liability_coverage_cents": 100_000_000,
        "max_overlapping_teams": 2,
        "visits_per_week_cap": 5,
    }
    defaults.update(overrides)
    return defaults


def create_facility_agreement_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "start_on": "2026-07-01",
        "end_on": "2027-06-30",
        "agreed_max_visit_minutes": 90,
        "insurance_minimum_cents": 100_000_000,
        "terms_version": "t1",
    }
    defaults.update(overrides)
    return defaults


def create_orientation_payload(team_id, **overrides) -> dict:
    payload = {"team_id": team_id}
    payload.update(overrides)
    return payload


def create_insurance_policy_payload(**overrides) -> dict:
    defaults = {
        "insurer_name": "Test Insurer",
        "policy_number": _unique_policy_number(),
        "coverage_cents": 200_000_000,
        "effective_from": "2026-01-01",
        "effective_until": "2029-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_liability_waiver_payload(team_id, facility_id, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "facility_id": facility_id,
        "waiver_version": "v1",
        "signed_on": "2026-08-02",
    }
    defaults.update(overrides)
    return defaults


def create_visit_request_payload(**overrides) -> dict:
    defaults = {
        "requested_start": "2026-08-10T14:00:00Z",
        "requested_end": "2026-08-10T15:00:00Z",
        "visit_program": "GENERAL",
        "priority": "ROUTINE",
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(team_id, facility_id, scheduled_start, scheduled_end,
                         expected_team_version, **overrides) -> dict:
    payload = {
        "team_id": team_id,
        "facility_id": facility_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_team_version": expected_team_version,
    }
    payload.update(overrides)
    return payload


def create_incident_payload(visit_id, **overrides) -> dict:
    defaults = {
        "visit_id": visit_id,
        "severity": "LOW",
        "category": "PROTOCOL_BREACH",
        "description": "handler skipped sign-in sheet",
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(handler_id, minutes, reason="manual adjustment", **overrides) -> dict:
    payload = {"handler_id": handler_id, "minutes": minutes, "reason": reason}
    payload.update(overrides)
    return payload
