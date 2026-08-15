"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
from .constants import PASSING_WEATHER, STANDARD_MATERIAL


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Dana Homeowner",
        "customer_type": "RESIDENTIAL",
        "email": "dana@example.com",
        "phone": "555-9001",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "address": "1 Elm St",
        "lot_kind": "RESIDENTIAL_DRIVEWAY",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "measured_area_sqft": 900,
        "crack_linear_ft": 10,
        "pothole_count": 1,
        "pothole_area_sqft": 2,
        "oil_spot_area_sqft": 0,
        "slope_severity": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    defaults = dict(STANDARD_MATERIAL)
    defaults.update(overrides)
    return defaults


def create_material_lot_payload(material_id, **overrides) -> dict:
    defaults = {
        "material_id": material_id,
        "delivered_gallons": 100,
        "unit_cost_cents": 1500,
        "received_on": "2026-07-15",
        "reorder_threshold_gallons": 15,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_name": "Crew Alpha",
        "home_zone": "North",
        "daily_capacity_sqft": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_route_sheet_payload(crew_id, service_date, **overrides) -> dict:
    defaults = {"crew_id": crew_id, "service_date": service_date}
    defaults.update(overrides)
    return defaults


def create_quote_payload(
    property_id, assessment_id, material_id, expected_property_version, **overrides
) -> dict:
    defaults = {
        "property_id": property_id,
        "assessment_id": assessment_id,
        "material_id": material_id,
        "include_crack_fill": True,
        "include_patch": True,
        "include_seal": True,
        "include_striping": False,
        "coats": 1,
        "expected_property_version": expected_property_version,
    }
    defaults.update(overrides)
    return defaults


def schedule_work_order_payload(route_sheet_id, material_lot_id, scheduled_date, **overrides) -> dict:
    defaults = {
        "route_sheet_id": route_sheet_id,
        "material_lot_id": material_lot_id,
        "scheduled_date": scheduled_date,
        "window_start_hour": 7,
        "window_end_hour": 11,
        "drive_minutes_est": 20,
        "vehicles_to_move": 3,
    }
    defaults.update(overrides)
    return defaults


def reschedule_work_order_payload(
    route_sheet_id, scheduled_date, expected_work_order_version, **overrides
) -> dict:
    defaults = {
        "route_sheet_id": route_sheet_id,
        "scheduled_date": scheduled_date,
        "window_start_hour": 8,
        "window_end_hour": 11,
        "drive_minutes_est": 20,
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def finish_application_payload(**overrides) -> dict:
    defaults = {
        "actual_area_sqft": 900,
        "actual_crack_ft": 10,
        "actual_pothole_area_sqft": 2,
        "actual_stripe_ft": 0,
        "gallons_used": 12,
    }
    defaults.update(overrides)
    return defaults


def create_weather_snapshot_payload(target_date, **overrides) -> dict:
    defaults = {"target_date": target_date}
    defaults.update(PASSING_WEATHER)
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(warranty_record_id, **overrides) -> dict:
    defaults = {
        "warranty_record_id": warranty_record_id,
        "claim_type": "PEELING",
        "description": "Coating defect within warranty",
    }
    defaults.update(overrides)
    return defaults
