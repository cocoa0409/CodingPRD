"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_dealership_payload(**overrides) -> dict:
    defaults = {
        "name": "DLR",
        "staging_capacity_units": TEST_DEFAULTS["STAGING_CAPACITY_UNITS"],
        "standard_labor_rate_cents_per_hour": TEST_DEFAULTS["STANDARD_LABOR_RATE_CENTS_PER_HOUR"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(dealership_id, **overrides) -> dict:
    defaults = {
        "dealership_id": dealership_id,
        "name": "Acme Corp",
        "external_ref": "ACME-1",
    }
    defaults.update(overrides)
    return defaults


def create_pricing_contract_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "contract_type": "STATE",
        "pricing_tiers": [{"category": "SEATING", "min_qty": 1, "discount_pct": 40}],
        "default_discount_pct": TEST_DEFAULTS["DEFAULT_DISCOUNT_PCT"],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_space_plan_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "name": "HQ Floor 3",
    }
    defaults.update(overrides)
    return defaults


def create_typical_payload(space_plan_id, **overrides) -> dict:
    defaults = {
        "space_plan_id": space_plan_id,
        "code": "WS-A",
        "quantity": TEST_DEFAULTS["TYPICAL_QUANTITY"],
        "target_budget_cents_per_instance": TEST_DEFAULTS["TYPICAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_series_payload(dealership_id, **overrides) -> dict:
    defaults = {
        "dealership_id": dealership_id,
        "manufacturer": "STEELCASE",
        "category": "SEATING",
        "series_code": "SC-ANS",
        "base_list_price_cents": TEST_DEFAULTS["BASE_LIST_PRICE_CENTS"],
        "base_lead_time_days": TEST_DEFAULTS["BASE_LEAD_TIME_DAYS"],
        "option_catalog": [],
    }
    defaults.update(overrides)
    return defaults


def create_project_order_payload(customer_id, contract_id, space_plan_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "contract_id": contract_id,
        "space_plan_id": space_plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(order_id, series_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "series_id": series_id,
        "quantity": 2,
        "selected_options": [],
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(dealership_id, **overrides) -> dict:
    defaults = {
        "dealership_id": dealership_id,
        "name": "Crew Alpha",
        "size": 4,
    }
    defaults.update(overrides)
    return defaults


def create_install_event_payload(order_id, crew_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "crew_id": crew_id,
        "kind": "NEW_INSTALL",
        "scheduled_date": "2026-08-10",
        "start_minute": 540,
        "end_minute": 720,
    }
    defaults.update(overrides)
    return defaults


def create_staging_reservation_payload(order_line_id, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "units": 5,
        "start_date": "2026-08-06",
        "end_date": "2026-08-08",
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "severity": "STANDARD",
        "description": "Scuff on panel",
    }
    defaults.update(overrides)
    return defaults


def create_manufacturer_claim_payload(punch_item_id, **overrides) -> dict:
    defaults = {
        "punch_item_id": punch_item_id,
        "claim_type": "DEFECT",
        "remedy_requested": "REPAIR",
        "claimed_amount_cents": 5_000,
    }
    defaults.update(overrides)
    return defaults


def create_asset_tag_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "description": "Task chair",
        "condition": "GOOD",
        "current_location": "Floor 3",
        "source": "PURCHASED",
    }
    defaults.update(overrides)
    return defaults


def create_liquidation_lot_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "description": "Trade-in lot",
        "item_count": 10,
    }
    defaults.update(overrides)
    return defaults
