"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from typing import Optional

DEFAULTS = {
    "SKU": "P-1000",
    "PRODUCT_NAME": "Widget",
    "CONTROLLED_CONTENT_PCT": 0,
    "UNIT_VALUE_CENTS": 1000,
    "JURISDICTION": "EAR",
    "CLASSIFICATION_CODE": "EAR99",
    "DETERMINATION_BASIS": "SELF_CLASSIFICATION",
    "LEGAL_NAME": "Clean Buyer Ltd",
    "COUNTRY_CODE": "GBR",
    "CITY": "London",
    "PARTY_TYPE": "CUSTOMER",
    "DESTINATION": "FRA",
    "END_USE": "CIVILIAN",
    "QUANTITY": 1,
    "ISSUING_AUTHORITY": "BIS",
    "APPROVED_VALUE_CENTS": 100000,
    "APPROVED_QUANTITY": 100,
    "VALID_FROM": "2026-07-01",
    "VALID_UNTIL": "2026-12-31",
    "PLANNED_SHIP_DATE": "2026-08-10",
    "TCP_NAME": "TCP-1",
    "ENCLAVE_ID": "LAB-1",
    "SEGREGATION_LEVEL": "LEVEL_1",
    "EFFECTIVE_FROM": "2026-01-01",
    "EFFECTIVE_TO": "2027-01-01",
    "GRANT_START": "2026-08-01",
    "GRANT_END": "2026-12-01",
    "LIST_SOURCE": "DENIED_PERSONS",
    "MATCH_NAME": "Listed Entity",
    "SEVERITY": "RESTRICTED",
    "SOURCE_TYPE": "OTHER",
    "SOURCE_ID": "n/a",
    "VIOLATION_SEVERITY": "MINOR",
    "DESCRIPTION": "Suspected compliance breach",
}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "controlled_content_pct": DEFAULTS["CONTROLLED_CONTENT_PCT"],
        "unit_value_cents": DEFAULTS["UNIT_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_classification_payload(product_id: str, expected_product_version: int, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "expected_product_version": expected_product_version,
        "jurisdiction": DEFAULTS["JURISDICTION"],
        "classification_code": DEFAULTS["CLASSIFICATION_CODE"],
        "determination_basis": DEFAULTS["DETERMINATION_BASIS"],
    }
    defaults.update(overrides)
    return defaults


def create_party_payload(is_foreign_national: Optional[bool] = None, **overrides) -> dict:
    """Party payload. is_foreign_national is OMITTED unless explicitly passed,
    so tests can exercise the PRD's server-side default of false (§3.2)."""
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "city": DEFAULTS["CITY"],
        "party_type": DEFAULTS["PARTY_TYPE"],
    }
    if is_foreign_national is not None:
        defaults["is_foreign_national"] = is_foreign_national
    defaults.update(overrides)
    return defaults


def create_screening_list_entry_payload(**overrides) -> dict:
    defaults = {
        "list_source": DEFAULTS["LIST_SOURCE"],
        "match_name": DEFAULTS["MATCH_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "severity": DEFAULTS["SEVERITY"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(product_id: str, party_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "party_id": party_id,
        "destination_country": DEFAULTS["DESTINATION"],
        "end_use": DEFAULTS["END_USE"],
        "quantity": DEFAULTS["QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(product_id: str, conditions: Optional[list] = None, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "issuing_authority": DEFAULTS["ISSUING_AUTHORITY"],
        "approved_value_cents": DEFAULTS["APPROVED_VALUE_CENTS"],
        "approved_quantity": DEFAULTS["APPROVED_QUANTITY"],
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    if conditions is not None:
        defaults["conditions"] = conditions
    defaults.update(overrides)
    return defaults


def create_shipment_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "quantity": DEFAULTS["QUANTITY"],
        "planned_ship_date": DEFAULTS["PLANNED_SHIP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_tcp_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TCP_NAME"],
        "enclave_id": DEFAULTS["ENCLAVE_ID"],
        "product_id": product_id,
        "segregation_level": DEFAULTS["SEGREGATION_LEVEL"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(tcp_id: str, party_id: str, **overrides) -> dict:
    defaults = {
        "tcp_id": tcp_id,
        "party_id": party_id,
        "start_date": DEFAULTS["GRANT_START"],
        "end_date": DEFAULTS["GRANT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(**overrides) -> dict:
    defaults = {
        "source_type": DEFAULTS["SOURCE_TYPE"],
        "source_id": DEFAULTS["SOURCE_ID"],
        "severity": DEFAULTS["VIOLATION_SEVERITY"],
        "description": DEFAULTS["DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults
