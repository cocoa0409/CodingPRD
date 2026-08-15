"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import (
    DEFAULT_CREW_CAPACITY_MINUTES,
    DEFAULT_GEOJSON,
    DEFAULT_IN_SERVICE_DATE,
    DEFAULT_WORK_DATE,
)

BUILDER_DEFAULTS = {
    "company_name": "Acme Homes",
    "contact_email": "ops@acme.example",
    "license_number": "ST-12345",
}


def create_builder_payload(**overrides) -> dict:
    payload = dict(BUILDER_DEFAULTS)
    payload.update(overrides)
    return payload


def create_service_application_payload(builder_id, **overrides) -> dict:
    payload = {
        "builder_id": builder_id,
        "service_address": "12 Main St",
        "city": "Springfield",
        "state_code": "IL",
        "postal_code": "62701",
        "requested_in_service_date": DEFAULT_IN_SERVICE_DATE,
    }
    payload.update(overrides)
    return payload


def create_appliance_load_payload(service_application_id, **overrides) -> dict:
    payload = {
        "service_application_id": service_application_id,
        "appliance_type": "FURNACE",
        "quantity": 1,
        "btuh_input_rating": 80000,
    }
    payload.update(overrides)
    return payload


def create_main_extension_payload(service_application_id, **overrides) -> dict:
    payload = {
        "service_application_id": service_application_id,
        "design_footage_ft": 100,
        "crossings": [],
        "rock_excavation_expected": False,
    }
    payload.update(overrides)
    return payload


def record_as_built_payload(**overrides) -> dict:
    payload = {
        "actual_footage_ft": 100,
        "actual_unit_cost_cents": 4500,
        "actual_rock_excavation": False,
        "actual_crossings": [],
    }
    payload.update(overrides)
    return payload


def payment_payload(**overrides) -> dict:
    payload = {"amount_cents": 1000, "method": "ACH"}
    payload.update(overrides)
    return payload


def refund_payload(**overrides) -> dict:
    payload = {"amount_cents": 1000, "method": "ACH"}
    payload.update(overrides)
    return payload


def create_permit_payload(service_application_id, **overrides) -> dict:
    payload = {
        "service_application_id": service_application_id,
        "permit_type": "ROAD_CUT",
        "jurisdiction": "City of Springfield",
        "crossings": [{"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0}],
    }
    payload.update(overrides)
    return payload


def create_field_crew_payload(**overrides) -> dict:
    payload = {
        "crew_name": "Crew A",
        "specialty": "GENERAL",
        "daily_capacity_minutes": DEFAULT_CREW_CAPACITY_MINUTES,
    }
    payload.update(overrides)
    return payload


def create_crew_booking_payload(service_application_id, field_crew_id, **overrides) -> dict:
    payload = {
        "service_application_id": service_application_id,
        "field_crew_id": field_crew_id,
        "work_date": DEFAULT_WORK_DATE,
        "start_minute": 540,
        "end_minute": 1020,
        "scope": "SERVICE_INSTALL",
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {"full_name": "Insp Ray", "certifications": ["PRESSURE_TEST"]}
    payload.update(overrides)
    return payload


def create_inspection_payload(service_application_id, inspector_id, **overrides) -> dict:
    payload = {
        "service_application_id": service_application_id,
        "inspector_id": inspector_id,
        "inspection_type": "PRESSURE_TEST",
        "inspection_date": "2026-08-12",
        "start_minute": 540,
        "end_minute": 660,
    }
    payload.update(overrides)
    return payload


def create_meter_set_payload(service_application_id, **overrides) -> dict:
    payload = {"service_application_id": service_application_id}
    payload.update(overrides)
    return payload


def create_purge_leak_test_payload(meter_set_id, **overrides) -> dict:
    payload = {
        "meter_set_id": meter_set_id,
        "purge_duration_min": 10,
        "test_pressure_psi": 15.0,
        "test_duration_min": 60,
        "observed_pressure_drop_psi": 0.200,
    }
    payload.update(overrides)
    return payload


def create_turn_on_event_payload(service_application_id, appliance_load_id, **overrides) -> dict:
    payload = {
        "service_application_id": service_application_id,
        "appliance_load_id": appliance_load_id,
    }
    payload.update(overrides)
    return payload


def complete_turn_on_payload(**overrides) -> dict:
    payload = {
        "co_reading_ppm": 2.0,
        "odor_detected": False,
        "ignition_verified": True,
        "venting_verified": True,
    }
    payload.update(overrides)
    return payload


def create_gis_as_built_payload(service_application_id, **overrides) -> dict:
    payload = {
        "service_application_id": service_application_id,
        "geometry_geojson": DEFAULT_GEOJSON,
        "pipe_material": "PE",
        "depth_inches": 24.0,
    }
    payload.update(overrides)
    return payload
