"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the create-payload defaults and lets callers
override any field. Optional fields (those with a PRD default) are omitted
unless explicitly supplied, so the server's default behavior is exercised.
"""


def create_breed_payload(**overrides) -> dict:
    payload = {
        "name": "Test Breed",
        "coat_type": "SMOOTH",
        "size_class": "MEDIUM",
        "base_service_minutes": 60,
    }
    payload.update(overrides)
    return payload


def create_service_tier_payload(**overrides) -> dict:
    payload = {
        "code": "FULL_GROOM",
        "base_price_cents": 6000,
        "duration_multiplier": 1.00,
    }
    payload.update(overrides)
    return payload


def create_add_on_payload(**overrides) -> dict:
    # requires_calm has a server default (false); omit unless overridden.
    payload = {
        "code": "DESHED",
        "price_cents": 2000,
        "duration_minutes": 30,
    }
    payload.update(overrides)
    return payload


def create_van_payload(**overrides) -> dict:
    # has_show_equipment defaults false on the server; omit unless overridden.
    payload = {
        "label": "Test Van",
        "max_stops": 5,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "email": "owner@example.com",
        "full_name": "Test Owner",
        "service_zip": "90001",
    }
    payload.update(overrides)
    return payload


def create_pet_payload(customer_id, breed_id, **overrides) -> dict:
    # coat_condition / behavioral_flag default on the server; omit unless overridden.
    payload = {
        "customer_id": customer_id,
        "breed_id": breed_id,
        "name": "Test Pet",
        "weight_lbs": 30,
    }
    payload.update(overrides)
    return payload


def create_vaccination_payload(**overrides) -> dict:
    payload = {
        "vaccine_type": "RABIES",
        "issued_on": "2026-01-01T00:00:00Z",
        "expires_on": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_groomer_payload(**overrides) -> dict:
    # handles_aggressive / status default on the server; omit unless overridden.
    payload = {
        "email": "groomer@example.com",
        "full_name": "Test Groomer",
        "skill_level": "SENIOR",
    }
    payload.update(overrides)
    return payload


def create_route_day_payload(van_id, **overrides) -> dict:
    payload = {
        "van_id": van_id,
        "service_date": "2026-06-10T00:00:00Z",
        "window_start": "2026-06-10T09:00:00Z",
        "window_end": "2026-06-10T17:00:00Z",
        "coverage_zip": "90001",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(pet_id, service_tier_id, **overrides) -> dict:
    # recurring_plan_id is optional; omit unless overridden.
    payload = {
        "pet_id": pet_id,
        "service_tier_id": service_tier_id,
    }
    payload.update(overrides)
    return payload


def attach_add_on_payload(add_on_id, **overrides) -> dict:
    payload = {"add_on_id": add_on_id}
    payload.update(overrides)
    return payload


def schedule_payload(route_day_id, slot_start, expected_route_day_version, **overrides) -> dict:
    payload = {
        "route_day_id": route_day_id,
        "slot_start": slot_start,
        "expected_route_day_version": expected_route_day_version,
    }
    payload.update(overrides)
    return payload


def create_recurring_plan_payload(pet_id, service_tier_id, **overrides) -> dict:
    payload = {
        "pet_id": pet_id,
        "service_tier_id": service_tier_id,
        "cadence_days": 28,
        "discount_pct": 0.05,
    }
    payload.update(overrides)
    return payload
