"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "OWNER_NAME": "Cattle Owner",
    "BILLING_EMAIL": "billing@example.com",
    "PEN_CODE": "P-01",
    "CAPACITY_HEAD": 100,
    "LOT_NUMBER": "L-100",
    "SEX_CLASS": "STEER",
    "HEAD_COUNT_IN": 10,
    "IN_WEIGHT_TOTAL_LBS": 7000,
    "PURCHASE_COST_CENTS": 1400000,
    "ARRIVAL_DATE": "2026-08-01",
    "RATION_NAME": "Starter-1",
    "STEP_LEVEL": 1,
    "COST_PER_TON_CENTS": 20000,
    "START_DATE": "2026-08-01",
    "HEAD_COUNT": 5,
    "RATION_WINDOW_END": "2026-08-10",
    "CALL_DATE": "2026-08-01",
    "BASE_QTY_LBS_PER_HEAD": 20.0,
    "DRUG_PRODUCT": "DRAXXIN",
    "WITHDRAWAL_DAYS": 0,
    "HEAD_TREATED": 1,
    "TREATMENT_COST_CENTS": 1000,
    "LOSS_DATE": "2026-08-01",
    "CAUSE": "RESPIRATORY",
    "CONTRACT_MONTH": "2026-12",
    "QUANTITY_CONTRACTS": 1,
    "ENTRY_PRICE_CENTS_PER_CWT": 19000,
    "EXIT_PRICE_CENTS_PER_CWT": 18900,
    "OFFSET_DATE": "2026-08-01",
    "GRID_BASE_PRICE_CENTS_PER_CWT": 19000,
    "PRICING_BASIS": "PER_CARCASS",
    "PAYMENT_DATE": "2026-08-01",
}


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "owner_name": f"{DEFAULTS['OWNER_NAME']}-{_seq()}",
        "billing_email": DEFAULTS["BILLING_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_pen_payload(**overrides) -> dict:
    defaults = {
        "pen_code": f"{DEFAULTS['PEN_CODE']}-{_seq()}",
        "capacity_head": DEFAULTS["CAPACITY_HEAD"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(owner_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "lot_number": f"{DEFAULTS['LOT_NUMBER']}-{_seq()}",
        "sex_class": DEFAULTS["SEX_CLASS"],
        "head_count_in": DEFAULTS["HEAD_COUNT_IN"],
        "in_weight_total_lbs": DEFAULTS["IN_WEIGHT_TOTAL_LBS"],
        "purchase_cost_cents": DEFAULTS["PURCHASE_COST_CENTS"],
        "arrival_date": DEFAULTS["ARRIVAL_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_ration_payload(**overrides) -> dict:
    defaults = {
        "ration_name": f"{DEFAULTS['RATION_NAME']}-{_seq()}",
        "step_level": DEFAULTS["STEP_LEVEL"],
        "cost_per_ton_cents": DEFAULTS["COST_PER_TON_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(pen_id, lot_id, **overrides) -> dict:
    defaults = {
        "pen_id": pen_id,
        "lot_id": lot_id,
        "head_count": DEFAULTS["HEAD_COUNT"],
        "start_date": DEFAULTS["START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_ration_assignment_payload(lot_id, ration_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "ration_id": ration_id,
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["RATION_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_feed_call_payload(pen_id, **overrides) -> dict:
    defaults = {
        "pen_id": pen_id,
        "call_date": DEFAULTS["CALL_DATE"],
        "base_qty_lbs_per_head": DEFAULTS["BASE_QTY_LBS_PER_HEAD"],
    }
    defaults.update(overrides)
    return defaults


def create_health_event_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "treatment_date": DEFAULTS["ARRIVAL_DATE"],
        "drug_product": DEFAULTS["DRUG_PRODUCT"],
        "withdrawal_days": DEFAULTS["WITHDRAWAL_DAYS"],
        "head_treated": DEFAULTS["HEAD_TREATED"],
        "treatment_cost_cents": DEFAULTS["TREATMENT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_death_loss_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "loss_date": DEFAULTS["LOSS_DATE"],
        "head_count": 1,
        "cause": DEFAULTS["CAUSE"],
        "insured": False,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_claim_payload(death_loss_id, **overrides) -> dict:
    defaults = {
        "death_loss_id": death_loss_id,
        "claimed_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_hedge_payload(lot_id, expected_lot_version, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "contract_month": DEFAULTS["CONTRACT_MONTH"],
        "quantity_contracts": DEFAULTS["QUANTITY_CONTRACTS"],
        "entry_price_cents_per_cwt": DEFAULTS["ENTRY_PRICE_CENTS_PER_CWT"],
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_close_out_payload(lot_id, expected_lot_version, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "pricing_basis": DEFAULTS["PRICING_BASIS"],
        "grid_base_price_cents_per_cwt": DEFAULTS["GRID_BASE_PRICE_CENTS_PER_CWT"],
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def carcass_record(**overrides) -> dict:
    defaults = {
        "hot_carcass_weight_lbs": 500,
        "quality_grade": "CHOICE",
        "yield_grade": 3,
    }
    defaults.update(overrides)
    return defaults
