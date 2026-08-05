"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DEFAULT_WINDOW_START": "2026-05-02T09:00:00Z",
    "DEFAULT_WINDOW_END": "2026-05-02T11:00:00Z",
    "ROUTE_WINDOW_START": "2026-05-02T06:00:00Z",
    "ROUTE_WINDOW_END": "2026-05-02T20:00:00Z",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "Test Customer", "email": "test@x.com", "customer_type": "INDIVIDUAL"}
    defaults.update(overrides)
    return defaults


def create_membership_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tier": "PLUS",
        "monthly_fee_cents": 3999,
        "included_deliveries": 5,
    }
    defaults.update(overrides)
    return defaults


def create_fleet_account_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "monthly_budget_cap_cents": 100000,
        "allowed_fuel_types": ["REGULAR"],
        "allowed_addons": [],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "make_model": "Test Vehicle",
        "fuel_type": "REGULAR",
        "tank_capacity_gallons": 40,
        "current_fuel_level_gallons": 0,
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    defaults = {"plate": "TRK-TEST", "home_zone": "ZONE_A"}
    defaults.update(overrides)
    return defaults


def create_compartment_payload(**overrides) -> dict:
    defaults = {"fuel_type": "REGULAR", "gallons_capacity": 200, "gallons_onboard": 100}
    defaults.update(overrides)
    return defaults


def create_route_payload(truck_id: str, assigned_driver_id: str, **overrides) -> dict:
    defaults = {
        "truck_id": truck_id,
        "assigned_driver_id": assigned_driver_id,
        "zone": "ZONE_A",
        "window_start": DEFAULTS["ROUTE_WINDOW_START"],
        "window_end": DEFAULTS["ROUTE_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, vehicle_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "zone": "ZONE_A",
        "delivery_address": "1 Main St",
        "requested_gallons": 10,
        "delivery_window_start": DEFAULTS["DEFAULT_WINDOW_START"],
        "delivery_window_end": DEFAULTS["DEFAULT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_fuel_price_payload(**overrides) -> dict:
    defaults = {
        "fuel_type": "REGULAR",
        "zone": "ZONE_A",
        "price_per_gallon_cents": 419,
        "effective_date": "2026-04-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(addon_type: str = "CAR_WASH", **overrides) -> dict:
    defaults = {"addon_type": addon_type}
    defaults.update(overrides)
    return defaults
