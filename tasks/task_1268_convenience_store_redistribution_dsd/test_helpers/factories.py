"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "STORE_NAME": "Test Store",
    "JURISDICTION": "CA_NORTH",
    "CREDIT_TERMS": "NET7",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "DELIVERY_DAY": "MON",
    "TOBACCO_LICENSE": "TLIC-9",
    "CUTOFF_HOURS_BEFORE": 24,
    "SKU": "P1",
    "DESCRIPTION": "test product",
    "CASE_PACK_UNITS": 12,
    "CASE_COST_CENTS": 1200,
    "UNIT_COST_CENTS": 110,
    "WEIGHT_LBS_PER_CASE": 10,
    "PROMO_TYPE": "OFF_INVOICE",
    "DISCOUNT_PCT_BPS": 1000,
    "PROMO_START": "2026-05-01",
    "PROMO_END": "2026-05-31",
    "SHELF_PRICE_CENTS": 199,
    "EFFECTIVE_START": "2026-05-01",
    "ROUTE_CODE": "R-1",
    "WINDOW_START": "2026-06-01T06:00:00Z",
    "WINDOW_END": "2026-06-01T08:00:00Z",
    "TURNAROUND_BUFFER_MINUTES": 30,
    "WEEK_START_DATE": "2026-05-25",
    "DOE_INDEX_USD": 3.75,
    "STAMP_RATE_CENTS_PER_PACK": 200,
    "HANDLING_FEE_PER_ROLL_CENTS": 1500,
    "PACKS_PER_ROLL": 6000,
    "MIN_CHARGE_CENTS": 5000,
    "DELIVERY_DATE": "2026-05-25",
    "CAPACITY_LBS": 100_000,
    "PROPOSED_SHELF_PRICE_CENTS": 999,
}


def create_retailer_payload(**overrides) -> dict:
    defaults = {
        "store_name": DEFAULTS["STORE_NAME"],
        "jurisdiction_code": DEFAULTS["JURISDICTION"],
        "credit_terms": DEFAULTS["CREDIT_TERMS"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "delivery_day": DEFAULTS["DELIVERY_DAY"],
        "tobacco_license_id": DEFAULTS["TOBACCO_LICENSE"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["SKU"],
        "description": DEFAULTS["DESCRIPTION"],
        "case_pack_units": DEFAULTS["CASE_PACK_UNITS"],
        "case_cost_cents": DEFAULTS["CASE_COST_CENTS"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "split_case_allowed": True,
        "is_tobacco": False,
        "weight_lbs_per_case": DEFAULTS["WEIGHT_LBS_PER_CASE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_guide_payload(**overrides) -> dict:
    defaults = {
        "retailer_id": None,
        "delivery_day": DEFAULTS["DELIVERY_DAY"],
        "cutoff_hours_before": DEFAULTS["CUTOFF_HOURS_BEFORE"],
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_promo_event_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "promo_type": DEFAULTS["PROMO_TYPE"],
        "discount_pct_bps": DEFAULTS["DISCOUNT_PCT_BPS"],
        "start_date": DEFAULTS["PROMO_START"],
        "end_date": DEFAULTS["PROMO_END"],
    }
    defaults.update(overrides)
    return defaults


def create_retail_price_record_payload(**overrides) -> dict:
    defaults = {
        "retailer_id": None,
        "product_id": None,
        "shelf_price_cents": DEFAULTS["SHELF_PRICE_CENTS"],
        "effective_start": DEFAULTS["EFFECTIVE_START"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_window_payload(**overrides) -> dict:
    defaults = {
        "route_code": DEFAULTS["ROUTE_CODE"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "turnaround_buffer_minutes": DEFAULTS["TURNAROUND_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_fuel_surcharge_rate_payload(**overrides) -> dict:
    defaults = {
        "week_start_date": DEFAULTS["WEEK_START_DATE"],
        "doe_index_usd": DEFAULTS["DOE_INDEX_USD"],
    }
    defaults.update(overrides)
    return defaults


def create_tax_stamp_supply_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction_code": DEFAULTS["JURISDICTION"],
        "stamp_rate_cents_per_pack": DEFAULTS["STAMP_RATE_CENTS_PER_PACK"],
        "handling_fee_per_roll_cents": DEFAULTS["HANDLING_FEE_PER_ROLL_CENTS"],
        "packs_per_roll": DEFAULTS["PACKS_PER_ROLL"],
        "min_charge_cents": DEFAULTS["MIN_CHARGE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_manifest_payload(**overrides) -> dict:
    defaults = {
        "route_code": DEFAULTS["ROUTE_CODE"],
        "delivery_date": DEFAULTS["DELIVERY_DATE"],
        "capacity_lbs": DEFAULTS["CAPACITY_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(**overrides) -> dict:
    defaults = {
        "retailer_id": None,
        "order_guide_id": None,
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, cases_qty=0, split_units_qty=0) -> dict:
    return {
        "product_id": product_id,
        "cases_qty": cases_qty,
        "split_units_qty": split_units_qty,
    }


def create_delivery_exception_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "order_line_id": None,
        "exception_type": "SHORT",
        "cases_qty": 0,
        "split_units_qty": 0,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 0,
        "method": "ACH",
    }
    defaults.update(overrides)
    return defaults


def create_credit_memo_payload(**overrides) -> dict:
    defaults = {
        "origin": "MANUAL",
        "amount_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_new_item_request_payload(**overrides) -> dict:
    defaults = {
        "retailer_id": None,
        "product_id": None,
        "proposed_shelf_price_cents": DEFAULTS["PROPOSED_SHELF_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults
