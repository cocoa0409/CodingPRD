"""Payload factories — one per entity, input fields only.

Required fields carry sensible defaults; optional fields are only included when
the caller passes them via **overrides (so omission tests stay faithful to the PRD).
"""

DEFAULTS = {
    "TAX_RATE": 0.0825,
    "TARGET_THROUGHPUT_SECONDS": 1800,
    "PACKAGE_BASE_PRICE_CENTS": 6995,
    "INCLUDED_QUARTS": 5,
    "LABOR_MINUTES": 20,
    "INTERVAL_MILES": 5000,
    "INTERVAL_DAYS": 180,
}


def create_shop_payload(**overrides) -> dict:
    """Required: name, tax_rate, target_throughput_seconds. Optional: max_discount_pct."""
    defaults = {
        "name": "Main",
        "tax_rate": DEFAULTS["TAX_RATE"],
        "target_throughput_seconds": DEFAULTS["TARGET_THROUGHPUT_SECONDS"],
    }
    defaults.update(overrides)
    return defaults


def create_service_package_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "oil_grade": "CONVENTIONAL",
        "name": "Basic Oil",
        "base_price_cents": DEFAULTS["PACKAGE_BASE_PRICE_CENTS"],
        "included_quarts": DEFAULTS["INCLUDED_QUARTS"],
        "labor_minutes": DEFAULTS["LABOR_MINUTES"],
        "interval_miles": DEFAULTS["INTERVAL_MILES"],
        "interval_days": DEFAULTS["INTERVAL_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_item_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "code": "AIR_FILTER",
        "name": "Air Filter",
        "price_cents": 4495,
        "labor_minutes": 5,
    }
    defaults.update(overrides)
    return defaults


def create_coupon_payload(shop_id, **overrides) -> dict:
    """Required: shop_id, code, discount_type, usage_limit. Optional: percent_value,
    flat_cents, min_subtotal_cents, stackable_with_fleet."""
    defaults = {
        "shop_id": shop_id,
        "code": "SAVE10",
        "discount_type": "PERCENT",
        "usage_limit": 5,
    }
    defaults.update(overrides)
    return defaults


def create_fleet_account_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "company_name": "Acme",
        "discount_pct": 0.10,
        "credit_limit_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(shop_id, **overrides) -> dict:
    """Required: shop_id, vin, plate, make, model, odometer. Optional: fleet_account_id."""
    defaults = {
        "shop_id": shop_id,
        "vin": "VIN0000001",
        "plate": "PLT1",
        "make": "Honda",
        "model": "Fit",
        "odometer": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_bay_payload(shop_id, **overrides) -> dict:
    """Required: shop_id, label. Optional: synthetic_certified."""
    defaults = {
        "shop_id": shop_id,
        "label": "Bay 1",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(shop_id, **overrides) -> dict:
    """Required: shop_id, full_name. Optional: synthetic_certified, cleanup_buffer_seconds."""
    defaults = {
        "shop_id": shop_id,
        "full_name": "Tess",
    }
    defaults.update(overrides)
    return defaults


def create_queue_ticket_payload(shop_id, vehicle_id, requested_package_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "vehicle_id": vehicle_id,
        "requested_package_id": requested_package_id,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(shop_id, vehicle_id, bay_id, package_id, odometer_in, **overrides) -> dict:
    """Required: shop_id, vehicle_id, bay_id, package_id, odometer_in. Optional: coupon_code."""
    defaults = {
        "shop_id": shop_id,
        "vehicle_id": vehicle_id,
        "bay_id": bay_id,
        "package_id": package_id,
        "odometer_in": odometer_in,
    }
    defaults.update(overrides)
    return defaults
