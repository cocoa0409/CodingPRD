"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "CUSTOMER_NAME": "ACME Bulk Co",
    "ALLOCATED_CAR_SPOTS": 5,
    "PRODUCT_NAME": "Salt",
    "HAZARD_CLASS": "NON_HAZARDOUS",
    "SEGREGATION_GROUP": "CHEMICAL",
    "REQUIRES_FULL_CLEAN": False,
    "TRACK_NAME": "T1",
    "SPOT_CAPACITY": 1,
    "EQUIPMENT_NAME": "PUMP-1",
    "EQUIPMENT_TYPE": "PUMP",
    "CAR_INITIALS": "WATX",
    "CAR_NUMBER": "10001",
    "QUANTITY_LOADED_TONS": 40.0,
    "SIT_DAILY_RATE_CENTS": 5000,
    "QUANTITY_PLANNED_TONS": 10.0,
    "TRUCK_REFERENCE": "TRK-1",
    "GROSS_WEIGHT_TONS": 24.0,
    "TARE_WEIGHT_TONS": 14.0,
    "TRUCK_MAX_PAYLOAD_TONS": 40.0,
    "PERIOD_START": "2026-08-01T00:00:00Z",
    "PERIOD_END": "2026-08-31T23:59:59Z",
    "WINDOW_START": "2026-08-03T01:00:00Z",
    "WINDOW_END": "2026-08-03T05:00:00Z",
    "SEVERITY": "MINOR",
    "INCIDENT_DESCRIPTION": "Routine safety observation",
}


def create_facility_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["FACILITY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "allocated_car_spots": DEFAULTS["ALLOCATED_CAR_SPOTS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "hazard_class": DEFAULTS["HAZARD_CLASS"],
        "segregation_group": DEFAULTS["SEGREGATION_GROUP"],
        "requires_full_clean": DEFAULTS["REQUIRES_FULL_CLEAN"],
    }
    defaults.update(overrides)
    return defaults


def create_track_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TRACK_NAME"],
        "spot_capacity": DEFAULTS["SPOT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["EQUIPMENT_NAME"],
        "equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "product_id": None,
        "sit_daily_rate_cents": DEFAULTS["SIT_DAILY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_railcar_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "product_id": None,
        "lot_id": None,
        "car_initials": DEFAULTS["CAR_INITIALS"],
        "car_number": DEFAULTS["CAR_NUMBER"],
        "quantity_loaded_tons": DEFAULTS["QUANTITY_LOADED_TONS"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "severity": DEFAULTS["SEVERITY"],
        "description": DEFAULTS["INCIDENT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_spot_order_payload(**overrides) -> dict:
    defaults = {
        "expected_railcar_version": None,
        "track_id": None,
        "spot_number": 1,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_order_payload(**overrides) -> dict:
    defaults = {
        "railcar_id": None,
        "equipment_id": None,
        "quantity_planned_tons": DEFAULTS["QUANTITY_PLANNED_TONS"],
    }
    defaults.update(overrides)
    return defaults


def create_weight_ticket_payload(**overrides) -> dict:
    defaults = {
        "truck_reference": DEFAULTS["TRUCK_REFERENCE"],
        "gross_weight_tons": DEFAULTS["GROSS_WEIGHT_TONS"],
        "tare_weight_tons": DEFAULTS["TARE_WEIGHT_TONS"],
        "truck_max_payload_tons": DEFAULTS["TRUCK_MAX_PAYLOAD_TONS"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def allocation_adjustment_payload(**overrides) -> dict:
    defaults = {
        "expected_customer_version": None,
        "new_allocated_car_spots": None,
    }
    defaults.update(overrides)
    return defaults
