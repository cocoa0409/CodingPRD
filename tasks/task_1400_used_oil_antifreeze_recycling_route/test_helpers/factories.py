"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Lube Co",
    "EPA_GENERATOR_ID": "EPAGEN000001",
    "SITE_ADDRESS": "1 Industrial Way",
    "DRIVER_NAME": "Test Driver",
    "ROUTE_CODE_PREFIX": "R",
    "VEHICLE_CAPACITY_GALLONS": 500,
    "TANK_CAPACITY_GALLONS": 500,
    "PRICE_CENTS_PER_GAL": 50,
    "RESALE_PRICE_CENTS_PER_GAL": 120,
    "FACILITY_NAME": "Test TSDF",
    "FACILITY_EPA_ID": "EPAID001",
    "FACILITY_DAILY_CAPACITY": 10000,
    "WINDOW_START": "08:00",
    "WINDOW_END": "09:00",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "epa_generator_id": DEFAULTS["EPA_GENERATOR_ID"],
        "market_zone": "NORTH",
        "credit_terms": "NET30",
    }
    defaults.update(overrides)
    return defaults


def create_tank_site_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "density_zone": "URBAN",
    }
    defaults.update(overrides)
    return defaults


def create_tank_payload(tank_site_id: str, **overrides) -> dict:
    defaults = {
        "tank_site_id": tank_site_id,
        "tank_kind": "USED_OIL",
        "capacity_gallons": DEFAULTS["TANK_CAPACITY_GALLONS"],
        "ownership": "CUSTOMER_OWNED",
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {
        "driver_name": DEFAULTS["DRIVER_NAME"],
        "cdl_class": "B",
        "hazmat_endorsement": True,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(driver_id: str, **overrides) -> dict:
    defaults = {
        "route_code": f"{DEFAULTS['ROUTE_CODE_PREFIX']}-1",
        "scheduled_date": "2026-08-05",
        "driver_id": driver_id,
        "vehicle_capacity_gallons": DEFAULTS["VEHICLE_CAPACITY_GALLONS"],
        "density_zone": "URBAN",
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(tank_site_id: str, tank_id: str, expected_route_version: int, **overrides) -> dict:
    defaults = {
        "tank_site_id": tank_site_id,
        "tank_id": tank_id,
        "scheduled_window_start": DEFAULTS["WINDOW_START"],
        "scheduled_window_end": DEFAULTS["WINDOW_END"],
        "sequence": 1,
        "estimated_volume_gallons": 100,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def create_sample_screening_payload(**overrides) -> dict:
    defaults = {
        "halogen_ppm": 10,
        "water_pct": 1.0,
        "ph_level": 7.0,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_ticket_payload(**overrides) -> dict:
    defaults = {
        "client_request_id": "PT-1",
        "metered_volume_gallons": 100,
    }
    defaults.update(overrides)
    return defaults


def create_settle_payload(expected_customer_version: int, **overrides) -> dict:
    defaults = {"expected_customer_version": expected_customer_version}
    defaults.update(overrides)
    return defaults


def create_adjust_payload(**overrides) -> dict:
    defaults = {"corrected_metered_volume_gallons": 80}
    defaults.update(overrides)
    return defaults


def create_disposal_facility_payload(**overrides) -> dict:
    defaults = {
        "facility_name": DEFAULTS["FACILITY_NAME"],
        "epa_id": DEFAULTS["FACILITY_EPA_ID"],
        "accepted_streams": ["USED_OIL"],
        "daily_capacity_gallons": DEFAULTS["FACILITY_DAILY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(disposal_facility_id: str, **overrides) -> dict:
    defaults = {
        "manifest_tracking_number": "MAN-001",
        "disposal_facility_id": disposal_facility_id,
    }
    defaults.update(overrides)
    return defaults


def create_blend_batch_payload(input_pickup_ticket_ids, **overrides) -> dict:
    defaults = {
        "batch_code": "BB-1",
        "target_product": "RE_REFINED_BASE_OIL",
        "input_pickup_ticket_ids": list(input_pickup_ticket_ids),
        "resale_price_cents_per_gal": DEFAULTS["RESALE_PRICE_CENTS_PER_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_spill_incident_payload(route_id: str, tank_site_id: str, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "tank_site_id": tank_site_id,
        "gallons_spilled": 7,
        "cause_code": "UNKNOWN",
    }
    defaults.update(overrides)
    return defaults


def create_market_price_payload(**overrides) -> dict:
    defaults = {
        "market_zone": "NORTH",
        "tank_kind": "USED_OIL",
        "effective_date": "2026-08-01",
        "price_cents_per_gal": DEFAULTS["PRICE_CENTS_PER_GAL"],
    }
    defaults.update(overrides)
    return defaults
