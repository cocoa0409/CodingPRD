"""Payload factories — one per creation endpoint, input fields only.

The node and SKU presets below are the reference configurations used across
the suite; every factory takes ``**overrides`` so a test can move exactly the
one input it cares about.
"""

# ------------------------------------------------------------ node presets
# Each preset is a complete POST /stores body.

NODE_PRESETS = {
    "S1": {
        "store_code": "S1-DOWNTOWN",
        "region_code": "WEST",
        "origin_zone": 4,
        "daily_unit_capacity": 120,
        "staffed_labor_minutes": 480,
        "labor_standard_minutes_per_order": 12,
        "pick_labor_minutes_per_unit": 3,
        "labor_rate_cents_per_minute": 42,
        "cutoff_utc_minutes": 1020,
        "hazmat_certified": False,
    },
    "S2": {
        "store_code": "S2-HARBOR",
        "region_code": "EAST",
        "origin_zone": 5,
        "daily_unit_capacity": 60,
        "staffed_labor_minutes": 300,
        "labor_standard_minutes_per_order": 15,
        "pick_labor_minutes_per_unit": 4,
        "labor_rate_cents_per_minute": 38,
        "cutoff_utc_minutes": 1080,
        "hazmat_certified": True,
    },
    "S3": {
        "store_code": "S3-SUBURB",
        "region_code": "WEST",
        "origin_zone": 2,
        "daily_unit_capacity": 200,
        "staffed_labor_minutes": 600,
        "labor_standard_minutes_per_order": 10,
        "pick_labor_minutes_per_unit": 2,
        "labor_rate_cents_per_minute": 20,
        "cutoff_utc_minutes": 960,
        "hazmat_certified": False,
    },
    "S4": {
        "store_code": "S4-KIOSK",
        "region_code": "WEST",
        "origin_zone": 4,
        "daily_unit_capacity": 50,
        "staffed_labor_minutes": 60,
        "labor_standard_minutes_per_order": 6,
        "pick_labor_minutes_per_unit": 3,
        "labor_rate_cents_per_minute": 30,
        "cutoff_utc_minutes": 1020,
        "hazmat_certified": False,
    },
    "S5": {
        "store_code": "S5-ANNEX",
        "region_code": "EAST",
        "origin_zone": 3,
        "daily_unit_capacity": 100,
        "staffed_labor_minutes": 400,
        "labor_standard_minutes_per_order": 10,
        "pick_labor_minutes_per_unit": 2,
        "labor_rate_cents_per_minute": 25,
        "cutoff_utc_minutes": 1020,
        "hazmat_certified": False,
    },
    "S6": {
        "store_code": "S6-OUTLET",
        "region_code": "WEST",
        "origin_zone": 4,
        "daily_unit_capacity": 100,
        "staffed_labor_minutes": 60,
        "labor_standard_minutes_per_order": 6,
        "pick_labor_minutes_per_unit": 3,
        "labor_rate_cents_per_minute": 30,
        "cutoff_utc_minutes": 1020,
        "hazmat_certified": False,
    },
    "S7": {
        "store_code": "S7-PHANTOM",
        "region_code": "WEST",
        "origin_zone": 3,
        "daily_unit_capacity": 40,
        "staffed_labor_minutes": 120,
        "labor_standard_minutes_per_order": 8,
        "pick_labor_minutes_per_unit": 2,
        "labor_rate_cents_per_minute": 25,
        "cutoff_utc_minutes": 1020,
        "hazmat_certified": False,
    },
    "S8": {
        "store_code": "S8-PHANTOM",
        "region_code": "WEST",
        "origin_zone": 3,
        "daily_unit_capacity": 40,
        "staffed_labor_minutes": 120,
        "labor_standard_minutes_per_order": 8,
        "pick_labor_minutes_per_unit": 2,
        "labor_rate_cents_per_minute": 25,
        "cutoff_utc_minutes": 1020,
        "hazmat_certified": False,
    },
    "S9": {
        "store_code": "S9-GHOST",
        "region_code": "WEST",
        "origin_zone": 3,
        "daily_unit_capacity": 40,
        "staffed_labor_minutes": 120,
        "labor_standard_minutes_per_order": 8,
        "pick_labor_minutes_per_unit": 2,
        "labor_rate_cents_per_minute": 25,
        "cutoff_utc_minutes": 1020,
        "hazmat_certified": False,
    },
}

# ------------------------------------------------------------- sku presets

SKU_PRESETS = {
    "SKU-A": {
        "sku_code": "SKU-A",
        "unit_weight_grams": 800,
        "unit_price_cents": 4500,
        "package_class": "MEDIUM",
        "hazmat_flag": False,
    },
    "SKU-B": {
        "sku_code": "SKU-B",
        "unit_weight_grams": 250,
        "unit_price_cents": 1900,
        "package_class": "SMALL",
        "hazmat_flag": False,
    },
    "SKU-H": {
        "sku_code": "SKU-H",
        "unit_weight_grams": 1200,
        "unit_price_cents": 6900,
        "package_class": "LARGE",
        "hazmat_flag": True,
    },
}


def create_store_payload(preset: str = "S1", **overrides) -> dict:
    payload = dict(NODE_PRESETS[preset])
    payload.update(overrides)
    return payload


def create_sku_payload(preset: str = "SKU-A", **overrides) -> dict:
    payload = dict(SKU_PRESETS[preset])
    payload.update(overrides)
    return payload


def create_store_inventory_payload(
    store_id: str, sku_id: str, on_hand_units: int = 12, safety_stock_units: int = 2,
    **overrides,
) -> dict:
    payload = {
        "store_id": store_id,
        "sku_id": sku_id,
        "on_hand_units": on_hand_units,
        "safety_stock_units": safety_stock_units,
    }
    payload.update(overrides)
    return payload


def create_packaging_supply_payload(
    store_id: str,
    package_type: str = "MEDIUM_BOX",
    on_hand_units: int = 20,
    reorder_point_units: int = 2,
    **overrides,
) -> dict:
    payload = {
        "store_id": store_id,
        "package_type": package_type,
        "on_hand_units": on_hand_units,
        "reorder_point_units": reorder_point_units,
    }
    payload.update(overrides)
    return payload


def create_carrier_pickup_payload(
    carrier_code: str = "GRD",
    window_start_utc: str = "2026-08-03T09:00:00Z",
    window_end_utc: str = "2026-08-03T12:00:00Z",
    parcel_capacity: int = 5,
    **overrides,
) -> dict:
    payload = {
        "carrier_code": carrier_code,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "parcel_capacity": parcel_capacity,
    }
    payload.update(overrides)
    return payload


def create_order_payload(
    order_code: str = "O-1001",
    customer_ref: str = "C-1",
    destination_zone: int = 4,
    service_level: str = "GROUND",
    promised_ship_by_utc: str = "2026-08-03T16:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "order_code": order_code,
        "customer_ref": customer_ref,
        "destination_zone": destination_zone,
        "service_level": service_level,
        "promised_ship_by_utc": promised_ship_by_utc,
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(
    sku_id: str, quantity: int = 2, unit_price_cents: int = 4500, **overrides
) -> dict:
    payload = {
        "sku_id": sku_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
    }
    payload.update(overrides)
    return payload


def create_routing_run_payload(
    expected_order_version: int, mode: str = "COMMIT", **overrides
) -> dict:
    payload = {"mode": mode, "expected_order_version": expected_order_version}
    payload.update(overrides)
    return payload


def inventory_adjustment_payload(
    expected_inventory_version: int,
    counted_on_hand_units: int,
    reason: str = "CYCLE_COUNT",
    **overrides,
) -> dict:
    payload = {
        "expected_inventory_version": expected_inventory_version,
        "counted_on_hand_units": counted_on_hand_units,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def pick_payload(picked_units: int, line_picks: list, **overrides) -> dict:
    payload = {"picked_units": picked_units, "line_picks": line_picks}
    payload.update(overrides)
    return payload


def line_pick(assignment_line_id: str, units_picked: int) -> dict:
    return {"assignment_line_id": assignment_line_id, "units_picked": units_picked}


def ship_payload(carrier_pickup_id: str, expected_pickup_version: int) -> dict:
    return {
        "carrier_pickup_id": carrier_pickup_id,
        "expected_pickup_version": expected_pickup_version,
    }
