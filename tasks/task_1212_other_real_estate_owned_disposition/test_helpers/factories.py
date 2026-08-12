"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_property_payload(**overrides) -> dict:
    defaults = {
        "address": "1420 Maple St",
        "state_code": "CA",
        "county": "Alameda",
        "property_type": "RESIDENTIAL",
        "acquisition_date": TEST_DEFAULTS["ACQ_DATE"],
        "bpo_value": TEST_DEFAULTS["BPO_VALUE"],
        "foreclosure_debt": TEST_DEFAULTS["FORECLOSURE_DEBT"],
    }
    defaults.update(overrides)
    return defaults


def create_appraiser_payload(**overrides) -> dict:
    defaults = {
        "name": "Apex Valuations",
        "license_number": "LIC-A1",
        "coverage_states": ["CA"],
        "fee_flat": TEST_DEFAULTS["FEE_FLAT"],
    }
    defaults.update(overrides)
    return defaults


def create_broker_payload(**overrides) -> dict:
    defaults = {
        "name": "Bay Brokers",
        "license_number": "LIC-B1",
        "coverage_states": ["CA"],
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(**overrides) -> dict:
    defaults = {
        "effective_date": TEST_DEFAULTS["APPRAISAL_EFFECTIVE"],
        "appraised_value": TEST_DEFAULTS["APPRAISAL_VALUE"],
    }
    defaults.update(overrides)
    return defaults


def create_listing_agreement_payload(**overrides) -> dict:
    defaults = {
        "start_date": TEST_DEFAULTS["LISTING_START"],
        "end_date": TEST_DEFAULTS["LISTING_END"],
        "listing_price": TEST_DEFAULTS["LISTING_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "buyer_name": "Buyer One",
        "offer_price": TEST_DEFAULTS["OFFER_PRICE"],
        "financing_type": "CASH",
        "earnest_money": TEST_DEFAULTS["EARNEST_MONEY"],
    }
    defaults.update(overrides)
    return defaults


def create_carrying_cost_payload(**overrides) -> dict:
    defaults = {
        "cost_type": "TAXES",
        "amount": 1200.00,
        "incurred_date": "2026-06-15",
    }
    defaults.update(overrides)
    return defaults


def create_issue_payload(**overrides) -> dict:
    defaults = {
        "issue_type": "TITLE",
        "severity": "MEDIUM",
        "description": "Unreleased lien",
    }
    defaults.update(overrides)
    return defaults


def create_write_down_payload(**overrides) -> dict:
    defaults = {
        "amount": 5000.00,
        "reason": "MARKET_DECLINE",
    }
    defaults.update(overrides)
    return defaults


def create_closing_statement_payload(**overrides) -> dict:
    defaults = {
        "closing_date": TEST_DEFAULTS["CLOSING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_extension_request_payload(**overrides) -> dict:
    defaults = {
        "requested_extension_days": 365,
        "justification": "Market conditions require extended marketing",
    }
    defaults.update(overrides)
    return defaults


def create_approval_tier_payload(**overrides) -> dict:
    defaults = {
        "name": "T1",
        "min_net_proceeds": 0.00,
        "max_net_proceeds": 250000.00,
        "required_role": "OREOSpecialist",
    }
    defaults.update(overrides)
    return defaults
