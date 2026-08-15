"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROGRAM_NAME": "2027 Seed Program",
    "CROP_YEAR": 2027,
    "ACCOUNT_NAME": "Smith Farms",
    "EXTERNAL_REF": "EXT-001",
    "CREDIT_LIMIT_CENTS": 100000000,
    "FIELD_NAME": "North 40",
    "FIELD_ACRES": 100,
    "VARIETY_SKU": "SOY-V2",
    "VARIETY_PRICE_CENTS": 18000,
    "SEEDS_PER_UNIT": 140000,
    "LOT_WAREHOUSE": "WH1",
    "LOT_RECEIVED_UNITS": 500,
    "LOT_EXPIRY": "2027-12-31T00:00:00Z",
    "AGREEMENT_FROM": "2026-08-01T00:00:00Z",
    "AGREEMENT_TO": "2027-12-31T23:59:59Z",
}


def create_program_payload(**overrides) -> dict:
    """Seed program create payload (PRD §3.1). Optional tier lists are omitted
    by default so their server-side empty-list defaults apply."""
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "crop_year": DEFAULTS["CROP_YEAR"],
        "early_order_tiers": [{"cutoff_at": "2027-01-15T23:59:59Z", "discount_bps": 600}],
        "return_window_end": "2027-06-30T23:59:59Z",
        "return_restocking_bps": 1000,
        "returns_untreated_only": True,
        "replant_claim_window_days": 21,
        "replant_replacement_discount_bps": 10000,
        "daily_delivery_capacity_units": 100000,
        "delivery_window_start": "2027-03-01T00:00:00Z",
        "delivery_window_end": "2027-05-31T23:59:59Z",
        "sales_close_at": "2027-03-15T23:59:59Z",
        "commission_base_bps": 500,
        "min_plot_replications": 2,
    }
    defaults.update(overrides)
    return defaults


def create_grower_payload(**overrides) -> dict:
    defaults = {
        "account_name": DEFAULTS["ACCOUNT_NAME"],
        "external_ref": DEFAULTS["EXTERNAL_REF"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_field_payload(grower_id, **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "name": DEFAULTS["FIELD_NAME"],
        "acres": DEFAULTS["FIELD_ACRES"],
        "soil_type": "LOAM",
        "drainage": "WELL",
        "irrigated": True,
        "prev_crop": "SOYBEAN",
        "maturity_zone": 11,
    }
    defaults.update(overrides)
    return defaults


def create_trait_package_payload(**overrides) -> dict:
    defaults = {
        "code": "VT2P",
        "description": "VT Double PRO",
        "requires_stewardship_agreement": True,
        "refuge_required_bps": 500,
    }
    defaults.update(overrides)
    return defaults


def create_variety_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["VARIETY_SKU"],
        "crop": "SOYBEAN",
        "relative_maturity_days": 118,
        "base_price_cents_per_unit": DEFAULTS["VARIETY_PRICE_CENTS"],
        "seeds_per_unit": DEFAULTS["SEEDS_PER_UNIT"],
        "preferred_soils": ["CLAY", "LOAM"],
        "min_drainage": "POOR",
    }
    defaults.update(overrides)
    return defaults


def create_trait_agreement_payload(grower_id, trait_package_id, expected_grower_version,
                                   **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "trait_package_id": trait_package_id,
        "effective_from": DEFAULTS["AGREEMENT_FROM"],
        "effective_to": DEFAULTS["AGREEMENT_TO"],
        "expected_grower_version": expected_grower_version,
    }
    defaults.update(overrides)
    return defaults


def create_recommendation_payload(field_id, variety_id, program_id, expected_field_version,
                                  **overrides) -> dict:
    defaults = {
        "field_id": field_id,
        "variety_id": variety_id,
        "program_id": program_id,
        "seeding_rate_seeds_per_acre": 34000,
        "expected_yield_index": 105,
        "expected_field_version": expected_field_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(grower_id, program_id, **overrides) -> dict:
    defaults = {"grower_id": grower_id, "program_id": program_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(variety_id, units, **overrides) -> dict:
    defaults = {"variety_id": variety_id, "units": units}
    defaults.update(overrides)
    return defaults


def create_treatment_option_payload(**overrides) -> dict:
    defaults = {"code": "FUNG-C", "crop": "CORN", "adder_cents_per_unit": 450}
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(variety_id, **overrides) -> dict:
    defaults = {
        "variety_id": variety_id,
        "warehouse_code": DEFAULTS["LOT_WAREHOUSE"],
        "received_units": DEFAULTS["LOT_RECEIVED_UNITS"],
        "expiry_date": DEFAULTS["LOT_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_ticket_payload(order_id, order_line_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "type": "DELIVERY",
        "scheduled_date": "2027-04-10T00:00:00Z",
        "units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(order_id, order_line_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "units": 1,
        "reason": "OVERSTOCK",
    }
    defaults.update(overrides)
    return defaults


def create_replant_claim_payload(order_id, order_line_id, field_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "field_id": field_id,
        "event_date": "2027-05-01T00:00:00Z",
        "event_type": "FROST",
        "acres_affected": 10,
    }
    defaults.update(overrides)
    return defaults


def create_plot_trial_payload(program_id, variety_id, field_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "variety_id": variety_id,
        "field_id": field_id,
        "planting_date": "2027-04-15T00:00:00Z",
        "expected_harvest_date": "2027-10-01T00:00:00Z",
        "replication_index": 1,
    }
    defaults.update(overrides)
    return defaults
