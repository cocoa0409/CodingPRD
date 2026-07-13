"""Payload factories — one per creatable entity, input fields only."""
import uuid

from .constants import (
    DEFAULT_SERVICE_DATE,
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
)


def _unique_email() -> str:
    return f"donor-{uuid.uuid4().hex[:12]}@example.com"


def create_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Charity",
        "region_code": "CA-BAY",
        "tax_id": "EIN-TEST",
        "accepted_categories": ["FURNITURE"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "label": "Truck-1",
        "capacity_cf": 200,
        "home_depot_code": "D1",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(vehicle_id: str, partner_id: str, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "partner_id": partner_id,
        "service_date": DEFAULT_SERVICE_DATE,
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Donor",
        "address": "1 Test St",
        "region_code": "CA-BAY",
    }
    defaults.update(overrides)
    return defaults


def create_pickup_request_payload(donor_id: str, partner_id: str, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "partner_id": partner_id,
        "pickup_mode": "ATTENDED",
        "disposition": "DONATION",
        "address": "1 Test St",
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "category": "FURNITURE",
        "volume_cf": 20,
        "weight_lbs": 5,
        "declared_value_cents": 1000,
        "declared_condition": "GOOD",
    }
    defaults.update(overrides)
    return defaults


def create_recurring_plan_payload(donor_id: str, partner_id: str, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "partner_id": partner_id,
        "pickup_mode": "ATTENDED",
        "address": "1 Test St",
        "default_disposition": "DONATION",
        "frequency": "WEEKLY",
    }
    defaults.update(overrides)
    return defaults


def schedule_payload(route_id: str, expected_route_version: int,
                     slot_start: str, slot_end: str, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults
