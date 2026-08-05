"""Payload factories — one per entity, input fields only."""


def create_district_payload(**overrides) -> dict:
    defaults = {
        "name": "Test District",
        "nces_code": "0601",
        "transport_budget_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_liaison_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "full_name": "Test Liaison",
        "email": "liaison@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(enrolled_district_id, origin_district_id=None, **overrides) -> dict:
    defaults = {
        "first_name": "Test",
        "last_name": "Student",
        "birthdate": "2012-01-01",
        "enrolled_district_id": enrolled_district_id,
        "origin_district_id": origin_district_id if origin_district_id is not None else enrolled_district_id,
        "living_situation": "SHELTER",
    }
    defaults.update(overrides)
    return defaults


def create_determination_payload(expected_student_version, **overrides) -> dict:
    defaults = {
        "category": "HOMELESS",
        "basis": "SHELTER",
        "decision": "ELIGIBLE",
        "effective_date": "2026-05-01",
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(student_id, origin_district_id, serving_district_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "origin_district_id": origin_district_id,
        "serving_district_id": serving_district_id,
        "route_miles": 20,
    }
    defaults.update(overrides)
    return defaults


def create_cost_share_payload(transportation_plan_id, expected_transportation_plan_version, **overrides) -> dict:
    defaults = {
        "transportation_plan_id": transportation_plan_id,
        "expected_transportation_plan_version": expected_transportation_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(serving_district_id, **overrides) -> dict:
    defaults = {
        "serving_district_id": serving_district_id,
        "label": "Bus1",
        "capacity_students": 24,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(transportation_plan_id, vehicle_id, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "transportation_plan_id": transportation_plan_id,
        "vehicle_id": vehicle_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "dispute_type": "ELIGIBILITY",
        "description": "Contest the determination.",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "subject": "MATH",
    }
    defaults.update(overrides)
    return defaults
