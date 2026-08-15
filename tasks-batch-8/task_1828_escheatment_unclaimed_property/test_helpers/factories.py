"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "OWNER_FULL_NAME": "Test Owner",
    "OWNER_ADDRESS": "1 Test St, Davis, CA",
    "STATE_CODE": "CA",
    "PROPERTY_TYPE": "SAVINGS",
    "DORMANCY_YEARS": 3,
    "EFFECTIVE_FROM": "2020-01-01",
    "ORIGINAL_VALUE_CENTS": 60000,
    "LAST_CONTACT_DATE": "2023-03-15",
    "REPORT_YEAR": 2026,
    "CUSIP": "ESC1828A",
    "SHARES_QUANTITY": 100,
    "LAST_CLOSE_PRICE_CENTS": 4500,
    "ACCRUED_DIVIDENDS_CENTS": 12500,
    "LIQUIDATION_FEE_CENTS": 2500,
    "EXECUTION_PRICE_CENTS_PER_SHARE": 4700,
}


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["OWNER_FULL_NAME"],
        "last_known_address": DEFAULTS["OWNER_ADDRESS"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_dormancy_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "property_type": DEFAULTS["PROPERTY_TYPE"],
        "dormancy_years": DEFAULTS["DORMANCY_YEARS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {
        "owner_id": None,
        "property_type": DEFAULTS["PROPERTY_TYPE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "original_value_cents": DEFAULTS["ORIGINAL_VALUE_CENTS"],
        "last_contact_date": DEFAULTS["LAST_CONTACT_DATE"],
    }
    defaults.update(overrides)
    return defaults


DEFAULT_CONTACT_DATE = "2026-08-01"


def create_contact_event_payload(**overrides) -> dict:
    defaults = {
        "contact_type": "WITHDRAWAL",
        "contact_date": DEFAULT_CONTACT_DATE,
        "evidence_ref": "ev-1",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "report_year": DEFAULTS["REPORT_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_securities_detail_payload(**overrides) -> dict:
    defaults = {
        "cusip": DEFAULTS["CUSIP"],
        "shares_quantity": DEFAULTS["SHARES_QUANTITY"],
        "last_close_price_cents": DEFAULTS["LAST_CLOSE_PRICE_CENTS"],
        "accrued_dividends_cents": DEFAULTS["ACCRUED_DIVIDENDS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_liquidation_order_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "liquidation_fee_cents": DEFAULTS["LIQUIDATION_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "lookback_start_year": 2020,
        "lookback_end_year": 2022,
    }
    defaults.update(overrides)
    return defaults


def create_document_record_payload(**overrides) -> dict:
    defaults = {
        "artifact_type": "REPORT_FILE",
        "related_entity_type": "HolderReport",
        "related_entity_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
    }
    defaults.update(overrides)
    return defaults
