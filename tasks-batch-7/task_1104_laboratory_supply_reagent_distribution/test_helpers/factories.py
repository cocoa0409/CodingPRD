"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "WAREHOUSE_NAME": "WH-NE",
    "REGION_CODE": "US-NE",
    "ZONE_CLASS": "AMBIENT",
    "ZONE_CAPACITY": 500,
    "SKU": "CH-1000",
    "PRODUCT_NAME": "Assay Vial",
    "STORAGE_REQUIREMENT": "AMBIENT",
    "HAZARD_CLASS": "NON_HAZARDOUS",
    "MAX_QTY_PER_SHIPMENT": 500,
    "UNIT_PRICE_CENTS": 1000,
    "SHELF_LIFE_DAYS": 365,
    "MIN_REMAINING_SHELF_LIFE_DAYS": 7,
    "CUSTOMER_NAME": "Lab Mu",
    "CREDIT_LIMIT_CENTS": 10000000,
    "QUANTITY_RECEIVED": 20,
    "MANUFACTURE_DATE": "2026-01-15",
    "SHIPPING_SERVICE": "STANDARD",
    "REQUESTED_SHIP_DATE": "2026-05-10",
}


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["WAREHOUSE_NAME"],
        "region_code": DEFAULTS["REGION_CODE"],
        "hazmat_certified": True,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "warehouse_id": None,
        "zone_class": DEFAULTS["ZONE_CLASS"],
        "capacity_units": DEFAULTS["ZONE_CAPACITY"],
        "rotation_policy": "FEFO",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "storage_requirement": DEFAULTS["STORAGE_REQUIREMENT"],
        "hazard_class": DEFAULTS["HAZARD_CLASS"],
        "max_qty_per_shipment": DEFAULTS["MAX_QTY_PER_SHIPMENT"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "requires_cold_chain": False,
        "shelf_life_days": DEFAULTS["SHELF_LIFE_DAYS"],
        "min_remaining_shelf_life_days": DEFAULTS["MIN_REMAINING_SHELF_LIFE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "warehouse_id": None,
        "storage_zone_id": None,
        "quantity_received": DEFAULTS["QUANTITY_RECEIVED"],
        "manufacture_date": DEFAULTS["MANUFACTURE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "warehouse_id": None,
        "shipping_service": DEFAULTS["SHIPPING_SERVICE"],
        "requested_ship_date": DEFAULTS["REQUESTED_SHIP_DATE"],
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, quantity, fulfillment_mode="ANY") -> dict:
    return {
        "product_id": product_id,
        "quantity": quantity,
        "fulfillment_mode": fulfillment_mode,
    }


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "coolant_type": "NONE",
        "coolant_units": 0,
        "declared_weight_grams": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_standing_order_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "product_id": None,
        "warehouse_id": None,
        "quantity_per_run": 2,
        "interval_days": 7,
        "effective_from": "2026-05-01",
        "effective_until": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "product_id": None,
        "ceiling_quantity": 100,
        "reorder_point": 0,
        "contract_unit_price_cents": 500,
        "replenishment_warehouse_id": None,
        "effective_from": "2026-05-01",
        "effective_until": "2027-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "scope_type": "PRODUCT_ALL",
        "severity_class": "CLASS_III",
        "reason": "Label defect",
    }
    defaults.update(overrides)
    return defaults


def create_kit_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "name": "Assay Starter Kit",
        "components": [],
    }
    defaults.update(overrides)
    return defaults


def kit_component(product_id, quantity_per_kit) -> dict:
    return {"product_id": product_id, "quantity_per_kit": quantity_per_kit}


def create_job_payload(**overrides) -> dict:
    defaults = {
        "kit_id": None,
        "warehouse_id": None,
        "quantity_to_build": 1,
    }
    defaults.update(overrides)
    return defaults
