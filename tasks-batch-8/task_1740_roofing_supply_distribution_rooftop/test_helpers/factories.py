"""Payload factories — one per creatable resource, input fields only (PRD §4)."""

from .constants import TEST_DEFAULTS as D


def create_branch_payload(**overrides) -> dict:
    defaults = {
        "branch_code": D["BRANCH_CODE"],
        "name": D["BRANCH_NAME"],
        "rooftop_delivery_capacity_per_day": D["ROOFTOP_CAPACITY_PER_DAY"],
        "conveyor_fleet_size": D["CONVEYOR_FLEET_SIZE"],
        "crane_available": True,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": D["SKU"],
        "manufacturer_name": D["MANUFACTURER"],
        "color_code": D["COLOR_CODE"],
        "bundles_per_square": D["BUNDLES_PER_SQUARE"],
        "base_price_per_bundle_cents": D["BASE_PRICE_PER_BUNDLE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def receive_inventory_lot_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "lot_code": D["LOT_CODE"],
        "on_hand_bundles": D["ON_HAND_BUNDLES"],
    }
    defaults.update(overrides)
    return defaults


def create_contractor_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": D["COMPANY_NAME"],
        "credit_limit_cents": D["CREDIT_LIMIT_CENTS"],
        "pricing_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_job_account_payload(**overrides) -> dict:
    defaults = {
        "job_name": D["JOB_NAME"],
        "site_address": D["SITE_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_takeoff_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "roof_squares": 5.0,
        "waste_factor_pct": 0,
        "valley_ridge_linear_feet": 0,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_date": D["SLOT_DATE"],
        "window": "AM",
        "equipment_type": "GROUND",
        "capacity": D["SLOT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_surge_event_payload(**overrides) -> dict:
    defaults = {
        "event_name": "Hail-Test",
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-08-31T23:59:59Z",
        "surge_multiplier_pct": 10,
        "allocation_pool_bundles": 1000,
    }
    defaults.update(overrides)
    return defaults


def request_allocation_payload(contractor_account_id, product_id, **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "product_id": product_id,
        "requested_bundles": 100,
    }
    defaults.update(overrides)
    return defaults


def request_return_payload(order_line_id, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "quantity_bundles": 1,
        "opened_bundles": 0,
    }
    defaults.update(overrides)
    return defaults


def file_damage_claim_payload(**overrides) -> dict:
    defaults = {
        "claimed_bundles": 1,
        "evidence_note": "Damaged on arrival",
    }
    defaults.update(overrides)
    return defaults


def post_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1,
    }
    defaults.update(overrides)
    return defaults
