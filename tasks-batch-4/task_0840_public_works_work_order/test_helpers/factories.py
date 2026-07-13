"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "INSTALL_DATE": "2024-01-01T00:00:00Z",
    "REPLACEMENT_VALUE_CENTS": 200000,
    "HOURLY_RATE_CENTS": 6000,
    "UNIT_COST_CENTS": 1200,
    "ON_HAND_QTY": 100,
}


def create_asset_payload(**overrides) -> dict:
    payload = {
        "asset_class": "ROAD",
        "gis_segment_id": "SEG-1",
        "location_desc": "Test location",
        "install_date": DEFAULTS["INSTALL_DATE"],
        "replacement_value_cents": DEFAULTS["REPLACEMENT_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides) -> dict:
    payload = {
        "asset_id": None,
        "inspection_type": "CONDITION",
        "raw_distress_index": 20,
        "scheduled_window_start": "2026-06-01T08:00:00Z",
        "scheduled_window_end": "2026-06-01T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_service_request_payload(**overrides) -> dict:
    payload = {
        "asset_id": None,
        "channel": "PHONE",
        "category": "POTHOLE",
        "reported_by": "Test Reporter",
        "location_desc": "Reported location",
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(**overrides) -> dict:
    payload = {
        "asset_id": None,
        "work_type": "MAINTENANCE",
        "origin": "PREVENTIVE",
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {
        "name": "Test Crew",
        "crew_type": "PAVING",
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_dispatch_payload(**overrides) -> dict:
    payload = {
        "work_order_id": None,
        "crew_id": None,
        "window_start": "2026-06-02T08:00:00Z",
        "window_end": "2026-06-02T12:00:00Z",
        "labor_hours": 4,
        "expected_crew_version": None,
    }
    payload.update(overrides)
    return payload


def create_yard_payload(**overrides) -> dict:
    payload = {
        "name": "Test Yard",
        "location_desc": "Central yard",
    }
    payload.update(overrides)
    return payload


def create_material_item_payload(**overrides) -> dict:
    payload = {
        "material_type": "ASPHALT_TON",
        "yard_id": None,
        "unit": "TON",
        "on_hand_qty": DEFAULTS["ON_HAND_QTY"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_material_reservation_payload(**overrides) -> dict:
    payload = {
        "work_order_id": None,
        "material_item_id": None,
        "qty": 5,
        "expected_material_item_version": None,
    }
    payload.update(overrides)
    return payload


def create_row_permit_payload(**overrides) -> dict:
    payload = {
        "work_order_id": None,
        "permit_type": "LANE_CLOSURE",
        "gis_segment_id": "SEG-1",
        "window_start": "2026-06-02T06:00:00Z",
        "window_end": "2026-06-02T20:00:00Z",
        "clearance_required": True,
    }
    payload.update(overrides)
    return payload
