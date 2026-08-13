"""Payload factories — one per entity, input fields only."""
from . import constants as C

DEFAULTS = {
    "PROGRAM_NAME": "P",
    "MARKET_NAME": "M",
    "MARKET_CITY": "C",
    "VENDOR_LEGAL_NAME": "V",
    "VENDOR_STALL": "S1",
    "SHOPPER_REF": "EBT-1",
    "BENEFIT_TYPE": "SNAP",
    "POOL_BUDGET_CENTS": 100000,
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "season_start": C.SEASON_START,
        "season_end": C.SEASON_END,
        "match_pool_budget_cents": DEFAULTS["POOL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_market_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "name": DEFAULTS["MARKET_NAME"],
        "city": DEFAULTS["MARKET_CITY"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "market_id": None,
        "legal_name": DEFAULTS["VENDOR_LEGAL_NAME"],
        "stall_number": DEFAULTS["VENDOR_STALL"],
    }
    defaults.update(overrides)
    return defaults


def create_shopper_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "external_benefit_ref": DEFAULTS["SHOPPER_REF"],
        "benefit_type": DEFAULTS["BENEFIT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_market_day_payload(**overrides) -> dict:
    defaults = {
        "market_id": None,
        "date": C.DAY_DATE,
        "opens_at": C.DAY_OPENS_AT,
        "closes_at": C.DAY_CLOSES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_token_batch_payload(**overrides) -> dict:
    defaults = {
        "market_id": None,
        "kind": "BASE",
        "denomination_cents": 100,
        "serial_start": C.BASE100_SERIAL_START,
        "serial_end": C.BASE100_SERIAL_END,
    }
    defaults.update(overrides)
    return defaults


def create_issuance_payload(**overrides) -> dict:
    defaults = {
        "shopper_id": None,
        "market_day_id": None,
        "benefit_charged_cents": 100,
        "expected_shopper_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(**overrides) -> dict:
    defaults = {
        "market_day_id": None,
        "token_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_fraud_case_payload(**overrides) -> dict:
    defaults = {"reason": "suspect"}
    defaults.update(overrides)
    return defaults


def create_settlement_run_payload(**overrides) -> dict:
    defaults = {
        "program_id": None,
        "cutoff_at": "2026-08-31T23:59:59Z",
        "expected_program_version": None,
    }
    defaults.update(overrides)
    return defaults
