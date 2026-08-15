"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_farm_payload(**overrides) -> dict:
    defaults = {
        "farm_number": f"F{1000 + _seq()}",
        "county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_producer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "producer_name": f"Producer {n}",
        "tax_id_last4": f"{n % 10000:04d}",
        "entity_type": "INDIVIDUAL",
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(**overrides) -> dict:
    defaults = {
        "producer_id": "",
        "share_percent": 100.00,
        "is_spouse_pair": False,
    }
    defaults.update(overrides)
    return defaults


def create_tract_payload(**overrides) -> dict:
    defaults = {
        "tract_number": f"T{_seq()}",
        "base_acres": TEST_DEFAULTS["BASE_ACRES"],
        "cropland_acres": TEST_DEFAULTS["BASE_ACRES"],
    }
    defaults.update(overrides)
    return defaults


def create_field_payload(**overrides) -> dict:
    defaults = {
        "field_number": f"{_seq()}",
        "acres": TEST_DEFAULTS["BASE_ACRES"],
    }
    defaults.update(overrides)
    return defaults


def create_acreage_report_payload(**overrides) -> dict:
    defaults = {"program_year": TEST_DEFAULTS["PROGRAM_YEAR"]}
    defaults.update(overrides)
    return defaults


def create_acreage_report_line_payload(**overrides) -> dict:
    defaults = {
        "field_id": "",
        "crop_code": TEST_DEFAULTS["COMMODITY"],
        "planted_acres": TEST_DEFAULTS["BASE_ACRES"],
        "prevented_planted_acres": 0.00,
        "intended_use": "GRAIN",
    }
    defaults.update(overrides)
    return defaults


def create_program_election_payload(**overrides) -> dict:
    defaults = {
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
        "commodity": TEST_DEFAULTS["COMMODITY"],
        "election_code": "PLC",
        "expected_farm_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_yield_record_payload(**overrides) -> dict:
    defaults = {"commodity": TEST_DEFAULTS["COMMODITY"]}
    defaults.update(overrides)
    return defaults


def create_yield_observation_payload(**overrides) -> dict:
    defaults = {"crop_year": 2021, "actual_yield_bu_per_acre": 180.0}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    defaults = {
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
        "commodity": TEST_DEFAULTS["COMMODITY"],
    }
    defaults.update(overrides)
    return defaults


def create_disaster_application_payload(**overrides) -> dict:
    defaults = {
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
        "disaster_type": "DROUGHT",
        "loss_acres": 40.00,
        "qualifying_commodity": TEST_DEFAULTS["COMMODITY"],
        "documentation_complete": True,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {
        "farm_id": "",
        "enrollment_id": "",
        "ground_code": "FACTUAL_ERROR",
        "filed_by_producer_id": "",
    }
    defaults.update(overrides)
    return defaults


def create_reconstitution_payload(**overrides) -> dict:
    defaults = {
        "method": "DIVIDE",
        "source_tract_ids": [],
        "product_specs": [],
        "expected_farm_version": 1,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def compute_payment_payload(**overrides) -> dict:
    defaults = {"national_my_price": TEST_DEFAULTS["MY_PRICE_TRIGGERING"]}
    defaults.update(overrides)
    return defaults
