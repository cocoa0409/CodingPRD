"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from typing import Optional

from .constants import (
    CONTRACT_END_DATE,
    CONTRACT_START_DATE,
    TAX_WINDOW_END,
    TAX_WINDOW_START,
    TEST_DEFAULTS,
    TEST_EFFECTIVE_DATE,
)


def create_terminal_payload(**overrides) -> dict:
    defaults = {
        "terminal_code": "T-01",
        "legal_name": "Test Terminal",
        "state_code": "TX",
        "county_code": "48201",
        "city_code": "HOU",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": "ULSD",
        "display_name": "Ultra Low Sulfur Diesel",
        "product_family": "DIESEL",
        "is_brandable": False,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "customer_code": "CUST-1",
        "legal_name": "Test Customer",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_contract_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "start_date": CONTRACT_START_DATE,
        "end_date": CONTRACT_END_DATE,
        "volume_commitment_gallons": TEST_DEFAULTS["VOLUME_COMMITMENT_GALLONS"],
        "pricing_tier": "RACK",
    }
    defaults.update(overrides)
    return defaults


def create_lifting_right_payload(customer_id: str, terminal_id: str,
                                 product_id: str, contract_id: str,
                                 **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "terminal_id": terminal_id,
        "product_id": product_id,
        "contract_id": contract_id,
        "daily_ratable_gallons": TEST_DEFAULTS["DAILY_RATABLE_GALLONS"],
    }
    defaults.update(overrides)
    return defaults


def create_price_schedule_payload(terminal_id: str, product_id: str,
                                  **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "product_id": product_id,
        "effective_date": TEST_EFFECTIVE_DATE,
        "posted_rack_cents_per_gal": TEST_DEFAULTS["POSTED_RACK_CENTS_PER_GAL"],
        "branded_premium_cents_per_gal": 0,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_notice_payload(terminal_id: str, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "effective_date": TEST_EFFECTIVE_DATE,
        "total_pool_gallons": 1000,
        "allocation_method": "PRO_RATA",
    }
    defaults.update(overrides)
    return defaults


def create_exchange_agreement_payload(delivering_terminal_id: str,
                                      product_id: str, **overrides) -> dict:
    defaults = {
        "delivering_terminal_id": delivering_terminal_id,
        "receiving_supplier_code": "EXT-1",
        "product_id": product_id,
        "monthly_exchange_cap_gallons": TEST_DEFAULTS["MONTHLY_EXCHANGE_CAP_GALLONS"],
    }
    defaults.update(overrides)
    return defaults


def create_lifting_ticket_payload(lifting_right_id: str, requested_gallons: int,
                                  branded: bool = False,
                                  additive_package_code: Optional[str] = None,
                                  **overrides) -> dict:
    payload = {
        "lifting_right_id": lifting_right_id,
        "requested_gallons": requested_gallons,
        "branded": branded,
    }
    if additive_package_code is not None:
        payload["additive_package_code"] = additive_package_code
    payload.update(overrides)
    return payload


def create_tax_rule_payload(jurisdiction_level: str, jurisdiction_code: str,
                            product_family: str, rate_cents_per_gal: int,
                            **overrides) -> dict:
    defaults = {
        "jurisdiction_level": jurisdiction_level,
        "jurisdiction_code": jurisdiction_code,
        "product_family": product_family,
        "rate_cents_per_gal": rate_cents_per_gal,
        "effective_start_date": TAX_WINDOW_START,
        "effective_end_date": TAX_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults
