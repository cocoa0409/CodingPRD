"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def unique_email(prefix="cust") -> str:
    return f"{prefix}{next(_counter)}@example.com"


def unique_asset_tag(prefix="EQ") -> str:
    return f"{prefix}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Customer",
        "service_zip": "10001",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "address": "1 Test St",
        "lawn_area_sqft": 3000,
        "zip": "10001",
    }
    defaults.update(overrides)
    return defaults


def create_preference_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "grass_height_mm": 40,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id, property_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "property_id": property_id,
        "season": "WINTER",
        "contract_price_cents": 10000,
        "term_months": 3,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "region_zip": "10001",
        "daily_capacity_minutes": 480,
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(route_id, property_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "property_id": property_id,
        "sequence": 1,
        "base_service_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(home_route_id, **overrides) -> dict:
    defaults = {
        "name": "Test Crew",
        "home_route_id": home_route_id,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": unique_asset_tag(),
        "equipment_type": "PLOW",
        "age_months": 12,
    }
    defaults.update(overrides)
    return defaults


def create_weather_reading_payload(**overrides) -> dict:
    defaults = {
        "region_zip": "10001",
        "snow_depth_in": 3.0,
        "observed_at": "2026-01-10T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(contract_id, route_stop_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "route_stop_id": route_stop_id,
        "service_type": "LAWN",
    }
    defaults.update(overrides)
    return defaults


def create_skip_request_payload(visit_id, **overrides) -> dict:
    defaults = {
        "visit_id": visit_id,
        "reason": "test reason",
    }
    defaults.update(overrides)
    return defaults
