"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from .constants import SIGNED_DATE, SSP_FULL_YEAR

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"legal_name": f"Customer {n}", "external_ref": f"EXT-{n}"}
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "customer_id": customer_id,
        "contract_ref": f"C-{n}",
        "signed_date": SIGNED_DATE,
        "fixed_consideration_cents": 100000,
        "risk_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_pob_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "pob_ref": f"P-{n}",
        "product_code": "WIDGET",
        "region": "US",
        "recognition_pattern": "POINT_IN_TIME",
    }
    defaults.update(overrides)
    return defaults


def create_ssp_price_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "product_code": f"PROD-{n}",
        "region": "US",
        "ssp_cents": 100000,
        "effective_from": SSP_FULL_YEAR["effective_from"],
        "effective_to": SSP_FULL_YEAR["effective_to"],
    }
    defaults.update(overrides)
    return defaults


def create_vc_estimate_payload(**overrides) -> dict:
    defaults = {
        "method": "MOST_LIKELY",
        "scenarios": [{"probability_bps": 10000, "amount_cents": 100000}],
    }
    defaults.update(overrides)
    return defaults


def create_modification_payload(expected_contract_version, **overrides) -> dict:
    defaults = {
        "mod_type": "CUMULATIVE_CATCH_UP",
        "delta_fixed_consideration_cents": 60000,
        "effective_date": "2026-06-15",
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_clause_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "clause_code": f"CL-{n}",
        "clause_type": "PENALTY",
        "is_non_standard": True,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "invoice_ref": f"INV-{n}",
        "amount_cents": 10000,
        "invoice_date": "2026-06-05",
    }
    defaults.update(overrides)
    return defaults


def create_accounting_period_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "period_code": f"2026-P{n}",
        "start_date": "2026-06-01",
        "end_date": "2026-07-01",
    }
    defaults.update(overrides)
    return defaults


def create_cost_entry_payload(**overrides) -> dict:
    defaults = {"amount_cents": 10000, "incurred_date": "2026-06-10"}
    defaults.update(overrides)
    return defaults
