"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ZONE_NAME": "Test Zone",
    "ZONE_CODE": "Z-TST",
    "BOND_COVERAGE_CENTS": 10_000_000_000,
    "ADMISSION_DESCRIPTION": "Merchandise",
    "HTS_CODE": "0401.10",
    "QUANTITY": 5,
    "UNIT_VALUE_CENTS": 1000,
    "ZONE_STATUS": "NON_PRIVILEGED_FOREIGN",
    "WITHDRAWAL_TYPE": "CONSUMPTION",
    "OUTPUT_HTS_CODE": "9503.00",
    "OUTPUT_DESCRIPTION": "Finished good",
    "WEEK_START_DATE": "2026-07-27T00:00:00Z",
    "ZONE_YEAR": 2026,
    "HOLDER_NAME": "Test Holder",
    "VALID_FROM": "2026-08-01T00:00:00Z",
    "VALID_UNTIL": "2026-12-31T00:00:00Z",
    "DIRECTION": "IN",
}


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ZONE_NAME"],
        "zone_code": DEFAULTS["ZONE_CODE"],
        "bond_coverage_cents": DEFAULTS["BOND_COVERAGE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_admission_payload(**overrides) -> dict:
    defaults = {
        "zone_id": None,
        "description": DEFAULTS["ADMISSION_DESCRIPTION"],
        "hts_code": DEFAULTS["HTS_CODE"],
        "quantity": DEFAULTS["QUANTITY"],
        "unit_value_cents": DEFAULTS["UNIT_VALUE_CENTS"],
        "zone_status": DEFAULTS["ZONE_STATUS"],
    }
    defaults.update(overrides)
    return defaults


def create_manipulation_order_payload(**overrides) -> dict:
    defaults = {
        "zone_id": None,
        "source_lot_id": None,
        "input_quantity": 1,
        "output_hts_code": DEFAULTS["OUTPUT_HTS_CODE"],
        "output_quantity": 1,
        "value_added_cents": 0,
        "output_description": DEFAULTS["OUTPUT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_payload(**overrides) -> dict:
    defaults = {
        "zone_id": None,
        "lot_id": None,
        "withdrawal_type": DEFAULTS["WITHDRAWAL_TYPE"],
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_weekly_entry_payload(**overrides) -> dict:
    defaults = {
        "zone_id": None,
        "week_start_date": DEFAULTS["WEEK_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_annual_reconciliation_payload(**overrides) -> dict:
    defaults = {
        "zone_id": None,
        "zone_year": DEFAULTS["ZONE_YEAR"],
        "beginning_value_cents": 0,
        "physical_ending_value_cents": 0,
        "expected_zone_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_access_badge_payload(**overrides) -> dict:
    defaults = {
        "zone_id": None,
        "holder_name": DEFAULTS["HOLDER_NAME"],
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_access_event_payload(**overrides) -> dict:
    defaults = {
        "zone_id": None,
        "badge_id": None,
        "direction": DEFAULTS["DIRECTION"],
    }
    defaults.update(overrides)
    return defaults
