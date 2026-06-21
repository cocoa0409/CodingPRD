"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying only client-supplied input fields. Server-
managed and computed fields (status, version, reserved_count, reliability_score,
provisional_hours, etc.) are never sent.
"""
import itertools

_email_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(prefix="vol"):
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_code(prefix="CODE"):
    return f"{prefix}_{next(_code_counter)}"


def create_organization_payload(**overrides) -> dict:
    payload = {"name": "Helping Hands"}
    payload.update(overrides)
    return payload


def create_volunteer_payload(organization_id, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "full_name": "Test Volunteer",
        "email": unique_email(),
    }
    payload.update(overrides)
    return payload


def create_background_check_payload(volunteer_id, requested_tier="BASIC", **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "requested_tier": requested_tier,
    }
    payload.update(overrides)
    return payload


def create_skill_payload(organization_id, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "code": unique_code("SKILL"),
        "label": "Test Skill",
    }
    payload.update(overrides)
    return payload


def create_volunteer_skill_payload(volunteer_id, skill_id, **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "skill_id": skill_id,
    }
    payload.update(overrides)
    return payload


def create_waiver_template_payload(organization_id, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "code": unique_code("WAIVER"),
    }
    payload.update(overrides)
    return payload


def create_waiver_acceptance_payload(volunteer_id, waiver_template_id, **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "waiver_template_id": waiver_template_id,
    }
    payload.update(overrides)
    return payload


def create_training_module_payload(organization_id, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "code": unique_code("TRAIN"),
    }
    payload.update(overrides)
    return payload


def create_training_completion_payload(volunteer_id, training_module_id, completed_at, **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "training_module_id": training_module_id,
        "completed_at": completed_at,
    }
    payload.update(overrides)
    return payload


def create_opportunity_payload(organization_id, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "title": "Test Opportunity",
    }
    payload.update(overrides)
    return payload


def create_shift_payload(opportunity_id, starts_at, ends_at, capacity, **overrides) -> dict:
    payload = {
        "opportunity_id": opportunity_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }
    payload.update(overrides)
    return payload


def create_signup_payload(volunteer_id, expected_shift_version, **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "expected_shift_version": expected_shift_version,
    }
    payload.update(overrides)
    return payload


def create_corporate_group_payload(opportunity_id, target_shift_id, requested_seats, **overrides) -> dict:
    payload = {
        "opportunity_id": opportunity_id,
        "sponsor_name": "Acme",
        "requested_seats": requested_seats,
        "target_shift_id": target_shift_id,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
