"""Payload factories — one per entity, input fields only."""


def create_depot_payload(**overrides) -> dict:
    defaults = {
        "name": "Central Yard",
        "salt_tons_on_hand": 100,
        "brine_gallons_on_hand": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(home_depot_id, **overrides) -> dict:
    defaults = {
        "home_depot_id": home_depot_id,
        "unit_number": "T1",
        "vehicle_type": "COMBO",
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Op A",
        "badge_number": "B2",
        "cdl_class": "A",
        "hourly_rate_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "name": "Main St",
        "tier": "ARTERIAL",
        "lane_miles": 2.0,
        "zone": "Z1",
    }
    defaults.update(overrides)
    return defaults


def create_storm_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Blizzard",
        "severity": "SEVERE",
        "forecast_start_at": "2026-02-10T00:00:00Z",
        "forecast_end_at": "2026-02-11T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_callout_payload(operator_id, **overrides) -> dict:
    defaults = {
        "operator_id": operator_id,
        "window_start_at": "2026-02-10T00:00:00Z",
        "window_end_at": "2026-02-10T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(route_id, vehicle_id, operator_id,
                              expected_storm_event_version, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "vehicle_id": vehicle_id,
        "operator_id": operator_id,
        "assignment_type": "PLOWING",
        "window_start_at": "2026-02-10T01:00:00Z",
        "window_end_at": "2026-02-10T05:00:00Z",
        "planned_material_tons": 2.0,
        "expected_storm_event_version": expected_storm_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(depot_id, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "material_type": "SALT",
        "salt_tons": 1.0,
        "lane_miles_treated": 2.0,
        "pavement_temp_f": 15,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(route_id, storm_event_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "storm_event_id": storm_event_id,
        "address": "12 Elm St",
        "complaint_type": "MISSED_STREET",
    }
    defaults.update(overrides)
    return defaults
