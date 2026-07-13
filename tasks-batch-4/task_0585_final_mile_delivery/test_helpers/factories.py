"""Payload factories — one per entity, input fields only."""


def create_depot_payload(**overrides) -> dict:
    defaults = {"name": "Depot A", "region_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_dock_payload(depot_id, **overrides) -> dict:
    defaults = {"depot_id": depot_id, "dock_code": "D1"}
    defaults.update(overrides)
    return defaults


def create_team_payload(depot_id, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "team_name": "T1",
        "lead_name": "Lee",
        "member2_name": "Max",
        "region_code": "CA",
        "max_daily_stops": 10,
        "max_daily_weight_lbs": 500,
        "max_daily_volume_cuft": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Cara",
        "address_line": "1 St",
        "region_code": "CA",
        "geo_lat": 34.0,
        "geo_lng": -118.0,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "item_description": "Table",
        "weight_lbs": 100,
        "volume_cuft": 20,
        "declared_value_cents": 10000,
        "service_level": "THRESHOLD",
    }
    defaults.update(overrides)
    return defaults


def reserve_window_payload(team_id, expected_order_version, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "service_date": "2026-06-01",
        "window_start_min": 480,
        "window_end_min": 600,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(depot_id, team_id, **overrides) -> dict:
    defaults = {"depot_id": depot_id, "team_id": team_id, "service_date": "2026-06-01"}
    defaults.update(overrides)
    return defaults


def add_stop_payload(order_id, window_id, **overrides) -> dict:
    defaults = {"order_id": order_id, "window_id": window_id}
    defaults.update(overrides)
    return defaults


def book_dock_appointment_payload(dock_id, **overrides) -> dict:
    defaults = {
        "dock_id": dock_id,
        "appt_date": "2026-06-01",
        "appt_start_min": 360,
        "appt_end_min": 420,
    }
    defaults.update(overrides)
    return defaults


def record_attempt_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults
