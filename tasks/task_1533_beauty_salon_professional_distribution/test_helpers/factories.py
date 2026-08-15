"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_consultant_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Consultant {_n()}",
        "territory_codes": [TEST_DEFAULTS["TERRITORY"]],
        "commission_model": "STRAIGHT",
    }
    defaults.update(overrides)
    return defaults


def create_salon_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Salon {_n()}",
        "territory_code": TEST_DEFAULTS["TERRITORY"],
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "license_number": f"LIC-{_n()}",
        "issuing_state": TEST_DEFAULTS["TERRITORY"],
        "license_type": "COSMETOLOGY",
        "valid_until": TEST_DEFAULTS["LICENSE_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_brand_payload(**overrides) -> dict:
    defaults = {"name": f"Brand{_n()}"}
    defaults.update(overrides)
    return defaults


def create_territory_exclusive_payload(**overrides) -> dict:
    defaults = {
        "territory_code": TEST_DEFAULTS["TERRITORY"],
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "sku": f"SKU-{n}",
        "name": f"Product {n}",
        "variant_type": "RETAIL",
        "hazmat_class": "NONE",
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
        "weight_grams": TEST_DEFAULTS["WEIGHT_GRAMS"],
    }
    defaults.update(overrides)
    return defaults


def create_route_plan_payload(**overrides) -> dict:
    defaults = {"name": f"Route {_n()}"}
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-08-10T09:00:00Z",
        "end_at": "2026-08-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {"items": []}
    defaults.update(overrides)
    return defaults


def create_order_item_payload(**overrides) -> dict:
    defaults = {"quantity": 1}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {"method": "GROUND", "items": []}
    defaults.update(overrides)
    return defaults


def create_sample_promotion_payload(**overrides) -> dict:
    defaults = {
        "code": f"SAMP{_n()}",
        "promo_type": "SAMPLE",
        "eligible_tiers": ["SILVER"],
        "starts_at": TEST_DEFAULTS["PROMO_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["PROMO_ENDS_AT"],
        "budget_units": 5,
        "per_salon_cap": 5,
        "sample_units_per_redemption": 1,
    }
    defaults.update(overrides)
    return defaults


def create_bundle_promotion_payload(**overrides) -> dict:
    defaults = {
        "code": f"BUN{_n()}",
        "promo_type": "BUNDLE",
        "eligible_tiers": ["SILVER"],
        "starts_at": TEST_DEFAULTS["PROMO_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["PROMO_ENDS_AT"],
        "budget_units": 10,
        "per_salon_cap": 5,
    }
    defaults.update(overrides)
    return defaults


def create_diversion_case_payload(**overrides) -> dict:
    defaults = {
        "severity": "MINOR",
        "evidence_note": "unauthorized retail listing observed",
        "hold_shipments": False,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
