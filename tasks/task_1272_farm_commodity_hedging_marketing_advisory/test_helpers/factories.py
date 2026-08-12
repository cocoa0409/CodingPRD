"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_op_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _op_counter["n"] += 1
    return f"{prefix} {_op_counter['n']}"


def create_operation_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("Test Farm"),
        "primary_commodity": "CORN",
        "crop_year": TEST_DEFAULTS["CROP_YEAR"],
        "risk_profile": "BALANCED",
    }
    defaults.update(overrides)
    return defaults


def create_baseline_payload(operation_id, expected_operation_version, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "planted_acres": TEST_DEFAULTS["PLANTED_ACRES"],
        "aph_yield_bushels": TEST_DEFAULTS["APH_YIELD"],
        "trend_yield_bushels": TEST_DEFAULTS["TREND_YIELD"],
        "expected_operation_version": expected_operation_version,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(operation_id, baseline_id, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "baseline_id": baseline_id,
        "coverage_level_pct": 0.75,
        "projected_price": 4.50,
    }
    defaults.update(overrides)
    return defaults


def file_claim_payload(**overrides) -> dict:
    defaults = {
        "actual_harvested_bushels": 0,
        "harvest_price": 4.50,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(operation_id, baseline_id, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "baseline_id": baseline_id,
        "max_priced_pct": 1.00,
    }
    defaults.update(overrides)
    return defaults


def amend_plan_payload(expected_marketing_plan_version, **overrides) -> dict:
    defaults = {"expected_marketing_plan_version": expected_marketing_plan_version}
    defaults.update(overrides)
    return defaults


def create_price_target_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "contract_month": TEST_DEFAULTS["CONTRACT_MONTH"],
        "target_price": 4.80,
        "increment_bushels": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_market_tick_payload(**overrides) -> dict:
    defaults = {
        "commodity": "CORN",
        "contract_month": TEST_DEFAULTS["CONTRACT_MONTH"],
        "price": 4.50,
        "kind": "SETTLEMENT",
        "price_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_recommendation_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "instrument": "FUTURES_SHORT",
        "contract_month": TEST_DEFAULTS["CONTRACT_MONTH"],
        "bushels": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_margin_account_payload(operation_id, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "initial_funding": 20000,
    }
    defaults.update(overrides)
    return defaults


def fund_margin_account_payload(amount, **overrides) -> dict:
    defaults = {"amount": amount}
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("Buyer"),
        "buyer_type": "ELEVATOR",
        "credit_rating": "A",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(operation_id, plan_id, buyer_id, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "plan_id": plan_id,
        "buyer_id": buyer_id,
        "contract_type": "FLAT_PRICE",
        "bushels": 1000,
        "fixed_price": TEST_DEFAULTS["FIXED_PRICE"],
        "delivery_window_start": TEST_DEFAULTS["WINDOW_START"],
        "delivery_window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def fix_price_payload(fixation_price, **overrides) -> dict:
    defaults = {"fixation_price": fixation_price}
    defaults.update(overrides)
    return defaults


def create_ticket_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "delivery_date": TEST_DEFAULTS["DELIVERY_DATE"],
        "gross_bushels": 1000,
        "moisture_pct": 15.0,
    }
    defaults.update(overrides)
    return defaults


def create_storage_lot_payload(operation_id, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "bin_id": "BIN-1",
        "bushels": 10000,
        "start_date": TEST_DEFAULTS["WINDOW_START"],
        "planned_end_date": "2026-12-31",
        "cost_per_bushel_month": 0.03,
        "annual_interest_rate": 0.06,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(operation_id, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "fee_type": "FLAT_ANNUAL",
        "flat_annual_fee": TEST_DEFAULTS["FLAT_ANNUAL_FEE"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
