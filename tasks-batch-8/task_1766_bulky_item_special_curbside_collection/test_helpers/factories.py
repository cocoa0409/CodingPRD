"""Payload factories — one per creatable entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_household_payload(**overrides) -> dict:
    defaults = {
        "street_address": TEST_DEFAULTS["STREET_ADDRESS"],
        "service_zone": TEST_DEFAULTS["SERVICE_ZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_amnesty_window_payload(**overrides) -> dict:
    defaults = {
        "label": "Test Amnesty Window",
        "starts_at": "2026-09-07T00:00:00Z",
        "ends_at": "2026-09-14T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_route_day_payload(**overrides) -> dict:
    defaults = {
        "service_zone": TEST_DEFAULTS["SERVICE_ZONE"],
        "route_date": "2026-08-10",
        "max_load_units": TEST_DEFAULTS["MAX_LOAD_UNITS"],
        "max_stops": TEST_DEFAULTS["MAX_STOPS"],
    }
    defaults.update(overrides)
    return defaults


def create_pickup_request_payload(household_id, **overrides) -> dict:
    defaults = {"household_id": household_id}
    defaults.update(overrides)
    return defaults


def create_item_payload(sequence_no=1, category="STANDARD_FURNITURE", **overrides) -> dict:
    defaults = {
        "sequence_no": sequence_no,
        "category": category,
        "is_oversize": False,
        "preparation_ack": True,
    }
    defaults.update(overrides)
    return defaults


def schedule_payload(route_day_id, expected_route_day_version) -> dict:
    return {
        "route_day_id": route_day_id,
        "expected_route_day_version": expected_route_day_version,
    }


def cancel_payload(expected_request_version) -> dict:
    return {"expected_request_version": expected_request_version}


def create_dumping_report_payload(household_id, **overrides) -> dict:
    defaults = {"household_id": household_id}
    defaults.update(overrides)
    return defaults


def determine_payload(determination, **overrides) -> dict:
    defaults = {"determination": determination}
    defaults.update(overrides)
    return defaults
