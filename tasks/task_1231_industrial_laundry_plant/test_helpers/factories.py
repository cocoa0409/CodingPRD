"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PLANT_NAME": "P",
    "REJECT_RATE_ALERT_PCT": 25.0,
    "PAR_SHORTAGE_ALERT_PIECES": 5,
    "UTILITY_BASELINE_KWH_PER_LB": 1.0,
    "UTILITY_BASELINE_GAL_PER_LB": 2.0,
    "CATEGORY_CODE": "TOWEL",
    "PIECE_WEIGHT_LB": 0.5,
    "WASH_FORMULA_CODE": "WF_STANDARD",
    "HYGIENIC_TEST_REQUIRED": False,
    "REPLACEMENT_COST_CENTS": 500,
    "COG_WASH_RATE_CENTS_PER_LB": 120,
    "CUSTOMER_NAME": "C",
    "CUSTOMER_KIND": "HOSPITALITY",
    "BILLING_MODE": "COG",
    "CHIP_TRACKING_ENABLED": False,
    "CREDIT_LIMIT_CENTS": 100000000,
    "SERVICE_DATE": "2026-05-02",
    "DRIVER_NAME": "D1",
    "SEQUENCE_INDEX": 1,
    "DECLARED_SOILED_WEIGHT_LB": 5.0,
    "CART_TAG": "CART-1",
    "SCALE_WEIGHT_LB": 5.0,
    "MACHINE_ID": "M1",
    "LINE_ID": "F1",
    "WASH_START": "2026-05-02T08:00:00Z",
    "WASH_END": "2026-05-02T09:00:00Z",
    "FINISH_START": "2026-05-02T09:00:00Z",
    "FINISH_END": "2026-05-02T10:00:00Z",
    "BILLING_PERIOD_START": "2026-05-01",
    "BILLING_PERIOD_END": "2026-06-01",
    "PERIOD_MONTH": "2026-05",
}


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PLANT_NAME"],
        "reject_rate_alert_pct": DEFAULTS["REJECT_RATE_ALERT_PCT"],
        "par_shortage_alert_pieces": DEFAULTS["PAR_SHORTAGE_ALERT_PIECES"],
        "utility_baseline_kwh_per_lb": DEFAULTS["UTILITY_BASELINE_KWH_PER_LB"],
        "utility_baseline_gal_per_lb": DEFAULTS["UTILITY_BASELINE_GAL_PER_LB"],
    }
    defaults.update(overrides)
    return defaults


def create_linen_category_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["CATEGORY_CODE"],
        "piece_weight_lb": DEFAULTS["PIECE_WEIGHT_LB"],
        "wash_formula_code": DEFAULTS["WASH_FORMULA_CODE"],
        "hygienic_test_required": DEFAULTS["HYGIENIC_TEST_REQUIRED"],
        "replacement_cost_cents": DEFAULTS["REPLACEMENT_COST_CENTS"],
        "cog_wash_rate_cents_per_lb": DEFAULTS["COG_WASH_RATE_CENTS_PER_LB"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "customer_kind": DEFAULTS["CUSTOMER_KIND"],
        "billing_mode": DEFAULTS["BILLING_MODE"],
        "chip_tracking_enabled": DEFAULTS["CHIP_TRACKING_ENABLED"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "service_date": DEFAULTS["SERVICE_DATE"],
        "driver_name": DEFAULTS["DRIVER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sequence_index": DEFAULTS["SEQUENCE_INDEX"],
        "declared_soiled_weight_lb": DEFAULTS["DECLARED_SOILED_WEIGHT_LB"],
    }
    defaults.update(overrides)
    return defaults


def pickup_payload(carts=None) -> dict:
    if carts is None:
        carts = [{
            "cart_tag": DEFAULTS["CART_TAG"],
            "scale_weight_lb": DEFAULTS["SCALE_WEIGHT_LB"],
        }]
    return {"carts": carts}


def create_sort_batch_payload(stop_id, **overrides) -> dict:
    defaults = {"stop_id": stop_id}
    defaults.update(overrides)
    return defaults


def create_sort_item_payload(category_id, pieces, disposition="ACCEPTED", **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "pieces": pieces,
        "disposition": disposition,
    }
    defaults.update(overrides)
    return defaults


def create_wash_load_payload(batch_id, category_id, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "category_id": category_id,
        "machine_id": DEFAULTS["MACHINE_ID"],
        "scheduled_start": DEFAULTS["WASH_START"],
        "scheduled_end": DEFAULTS["WASH_END"],
    }
    defaults.update(overrides)
    return defaults


def create_finish_run_payload(wash_load_id, **overrides) -> dict:
    defaults = {
        "wash_load_id": wash_load_id,
        "line_id": DEFAULTS["LINE_ID"],
        "scheduled_start": DEFAULTS["FINISH_START"],
        "scheduled_end": DEFAULTS["FINISH_END"],
    }
    defaults.update(overrides)
    return defaults


def register_garment_payload(customer_id, category_id, chip_code, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "category_id": category_id,
        "chip_code": chip_code,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(category_id, pieces_promised, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "pieces_promised": pieces_promised,
    }
    defaults.update(overrides)
    return defaults


def mark_delivered_payload(pieces_delivered, expected_customer_version) -> dict:
    return {
        "pieces_delivered": pieces_delivered,
        "expected_customer_version": expected_customer_version,
    }


def file_dispute_payload(claimed_shortfall_pieces) -> dict:
    return {"claimed_shortfall_pieces": claimed_shortfall_pieces}


def generate_invoice_payload(**overrides) -> dict:
    defaults = {
        "billing_period_start": DEFAULTS["BILLING_PERIOD_START"],
        "billing_period_end": DEFAULTS["BILLING_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_utility_reading_payload(**overrides) -> dict:
    defaults = {
        "period_month": DEFAULTS["PERIOD_MONTH"],
        "kwh_used": 1000,
        "gallons_used": 2000,
        "clean_lbs_processed": 1000,
        "kwh_rate_cents": 10,
        "gallon_rate_cents": 2,
    }
    defaults.update(overrides)
    return defaults
