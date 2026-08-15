"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MEMBERSHIP_NUMBER": "MB-1",
    "LEGAL_NAME": "Test Farm",
    "GRADE_CODE": "31-3",
    "PREMIUM_DISCOUNT_POINTS": 265,
    "LOAN_RATE_POINTS": 5450,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-01-01T00:00:00Z",
    "WAREHOUSE_NAME": "WH-1",
    "CAPACITY_BALES": 5,
    "DOCK_COUNT": 1,
    "SEASON": "2026",
    "STAND_LABEL": "STAND-A",
    "TICKET_NUMBER": "T-1",
    "MODULE_TAG": "MT-1",
    "GROSS_WEIGHT_LBS": 11000,
    "TARE_WEIGHT_LBS": 1000,
    "MOISTURE_PCT": 8.0,
    "FOREIGN_MATTER_PCT": 4.0,
    "BALE_TAG": "B-01",
    "BALE_NET_WEIGHT_LBS": 500,
    "MICRONAIRE": 4.0,
    "STRENGTH_GPT": 28.0,
    "STAPLE_32NDS": 36,
    "CLASSING_OFFICE": "USDA-MEMPHIS",
    "RESULT_DATE": "2026-03-10T00:00:00Z",
    "BUYER_NAME": "Delta Oil Mill",
    "PRICE_CENTS_PER_LB": 20,
    "MEMO": "manual correction",
    "LOAD_START": "2026-08-10T10:00:00Z",
    "LOAD_END": "2026-08-10T11:00:00Z",
    "REJECT_REASON": "contamination",
}


def create_grower_payload(**overrides) -> dict:
    defaults = {
        "membership_number": DEFAULTS["MEMBERSHIP_NUMBER"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_grade_schedule_payload(**overrides) -> dict:
    defaults = {
        "grade_code": DEFAULTS["GRADE_CODE"],
        "premium_discount_points": DEFAULTS["PREMIUM_DISCOUNT_POINTS"],
        "loan_rate_points": DEFAULTS["LOAN_RATE_POINTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["WAREHOUSE_NAME"],
        "capacity_bales": DEFAULTS["CAPACITY_BALES"],
        "dock_count": DEFAULTS["DOCK_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_gin_shift_payload(**overrides) -> dict:
    defaults = {
        "season": DEFAULTS["SEASON"],
        "stand_label": DEFAULTS["STAND_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def create_module_payload(grower_id, **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "season": DEFAULTS["SEASON"],
        "ticket_number": DEFAULTS["TICKET_NUMBER"],
        "module_tag": DEFAULTS["MODULE_TAG"],
        "gross_weight_lbs": DEFAULTS["GROSS_WEIGHT_LBS"],
        "tare_weight_lbs": DEFAULTS["TARE_WEIGHT_LBS"],
        "moisture_pct": DEFAULTS["MOISTURE_PCT"],
        "foreign_matter_pct": DEFAULTS["FOREIGN_MATTER_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_bale_entry(**overrides) -> dict:
    defaults = {
        "bale_tag": DEFAULTS["BALE_TAG"],
        "net_weight_lbs": DEFAULTS["BALE_NET_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_classing_result_payload(expected_bale_version, **overrides) -> dict:
    defaults = {
        "grade_code": DEFAULTS["GRADE_CODE"],
        "micronaire": DEFAULTS["MICRONAIRE"],
        "strength_gpt": DEFAULTS["STRENGTH_GPT"],
        "staple_32nds": DEFAULTS["STAPLE_32NDS"],
        "classing_office": DEFAULTS["CLASSING_OFFICE"],
        "result_date": DEFAULTS["RESULT_DATE"],
        "expected_bale_version": expected_bale_version,
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_receipt_payload(bale_id, warehouse_id, **overrides) -> dict:
    defaults = {"bale_id": bale_id, "warehouse_id": warehouse_id}
    defaults.update(overrides)
    return defaults


def create_loan_pledge_payload(warehouse_receipt_id, **overrides) -> dict:
    defaults = {"warehouse_receipt_id": warehouse_receipt_id}
    defaults.update(overrides)
    return defaults


def create_seed_sale_payload(gin_shift_id, **overrides) -> dict:
    defaults = {
        "gin_shift_id": gin_shift_id,
        "buyer_name": DEFAULTS["BUYER_NAME"],
        "price_cents_per_lb": DEFAULTS["PRICE_CENTS_PER_LB"],
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(season, expected_grower_version, **overrides) -> dict:
    defaults = {
        "season": season,
        "expected_grower_version": expected_grower_version,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_adjustment_payload(**overrides) -> dict:
    defaults = {
        "season": DEFAULTS["SEASON"],
        "amount_cents": 1000,
        "memo": DEFAULTS["MEMO"],
    }
    defaults.update(overrides)
    return defaults


def create_shipping_order_payload(warehouse_id, grower_id, bale_ids, **overrides) -> dict:
    defaults = {
        "warehouse_id": warehouse_id,
        "grower_id": grower_id,
        "bale_ids": bale_ids,
        "dock_number": 1,
        "load_start": DEFAULTS["LOAD_START"],
        "load_end": DEFAULTS["LOAD_END"],
    }
    defaults.update(overrides)
    return defaults
