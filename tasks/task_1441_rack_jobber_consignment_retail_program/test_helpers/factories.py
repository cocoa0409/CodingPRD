"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_program_payload(**overrides) -> dict:
    defaults = {"name": _seq("Program")}
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "name": _seq("Store"),
        "store_code": _seq("SC"),
        "total_facings": TEST_DEFAULTS["STORE_TOTAL_FACINGS"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(program_id: str, store_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "store_id": store_id,
        "base_margin_pct": TEST_DEFAULTS["BASE_MARGIN_PCT"],
        "shrink_retailer_share_pct": TEST_DEFAULTS["SHRINK_RETAILER_SHARE_PCT"],
        "restock_value_cap_cents": TEST_DEFAULTS["RESTOCK_VALUE_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "sku": _seq("SKU"),
        "name": _seq("Product"),
        "jobber_cost_cents": TEST_DEFAULTS["JOBBER_COST_CENTS"],
        "min_retail_cents": TEST_DEFAULTS["MIN_RETAIL_CENTS"],
        "units_per_facing": TEST_DEFAULTS["UNITS_PER_FACING"],
    }
    defaults.update(overrides)
    return defaults


def create_space_allocation_payload(store_agreement_id: str, **overrides) -> dict:
    defaults = {
        "store_agreement_id": store_agreement_id,
        "category": "SNACKS",
        "facings": 4,
        "window_start_date": "2026-08-01",
        "window_end_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_price_directive_payload(store_agreement_id: str, product_id: str,
                                   expected_store_agreement_version: int,
                                   **overrides) -> dict:
    defaults = {
        "store_agreement_id": store_agreement_id,
        "product_id": product_id,
        "price_cents": TEST_DEFAULTS["DIRECTIVE_PRICE_CENTS"],
        "effective_from": "2026-08-01T00:00:00Z",
        "expected_store_agreement_version": expected_store_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_promotion_payload(program_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "product_id": product_id,
        "name": _seq("Promo"),
        "depth_pct": 0.10,
        "jobber_funding_pct": 0.5,
        "start_date": "2026-08-01",
        "end_date": "2026-08-05",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": _seq("Route"),
        "assigned_driver_id": TEST_DEFAULTS["DRIVER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(route_id: str, store_agreement_id: str,
                                 **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "store_agreement_id": store_agreement_id,
        "scheduled_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def visit_count_line(product_id: str, counted_units: int,
                     restock_units: int) -> dict:
    return {
        "product_id": product_id,
        "counted_units": counted_units,
        "restock_units": restock_units,
    }


def create_scan_event_payload(store_agreement_id: str, product_id: str,
                              **overrides) -> dict:
    defaults = {
        "store_agreement_id": store_agreement_id,
        "product_id": product_id,
        "event_type": "SALE",
        "quantity": 1,
        "scanned_at": "2026-08-01T09:00:00Z",
        "client_event_id": _seq("evt"),
    }
    defaults.update(overrides)
    return defaults


def create_audit_count_payload(store_agreement_id: str, **overrides) -> dict:
    defaults = {
        "store_agreement_id": store_agreement_id,
        "scope": "FULL",
    }
    defaults.update(overrides)
    return defaults


def audit_counted_line(product_id: str, counted_units: int) -> dict:
    return {"product_id": product_id, "counted_units": counted_units}


def create_markdown_authorization_payload(store_agreement_id: str,
                                          product_id: str, **overrides) -> dict:
    defaults = {
        "store_agreement_id": store_agreement_id,
        "product_id": product_id,
        "auth_type": "MARKDOWN",
        "units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_statement_payload(store_agreement_id: str,
                                        period_index: int = 0,
                                        **overrides) -> dict:
    defaults = {
        "store_agreement_id": store_agreement_id,
        "period_index": period_index,
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_set_payload(store_agreement_id: str, **overrides) -> dict:
    defaults = {
        "store_agreement_id": store_agreement_id,
        "theme": _seq("Theme"),
        "category": "SEASONAL",
        "allocated_facings": 2,
        "set_window_start": "2026-08-05",
        "set_window_end": "2026-08-10",
        "teardown_deadline": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults
