"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import CIAC_FAR_EXPIRY, PERIOD_2026_08, TEST_DEFAULTS

_program_seq = {"n": 0}


def _next_code(prefix="CAP"):
    """Unique program codes so duplicate-code validation never trips within a
    test (the PRD rejects a duplicate code with ERR_VALIDATION)."""
    _program_seq["n"] += 1
    return f"{prefix}-{ _program_seq['n']:04d}"


def create_capital_program_payload(**overrides) -> dict:
    defaults = {
        "code": _next_code(),
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "authorized_amount_cents": TEST_DEFAULTS["AUTHORIZED_AMOUNT_CENTS"],
        "afudc_debt_rate_pct": TEST_DEFAULTS["AFUDC_DEBT_RATE_PCT"],
        "afudc_equity_rate_pct": TEST_DEFAULTS["AFUDC_EQUITY_RATE_PCT"],
        "afudc_debt_weight_pct": TEST_DEFAULTS["AFUDC_DEBT_WEIGHT_PCT"],
        "afudc_method": TEST_DEFAULTS["AFUDC_METHOD"],
        "ciac_method": TEST_DEFAULTS["CIAC_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_catalog_payload(**overrides) -> dict:
    defaults = {
        "asset_class": "TRANSFORMER",
        "standard_cost_cents": 50_000,
        "annual_depreciation_rate_pct": 12.0,
    }
    defaults.update(overrides)
    return defaults


def create_overhead_schedule_payload(**overrides) -> dict:
    defaults = {
        "cost_type": "MATERIAL",
        "order_type": "CAPITAL",
        "rate_pct": 0.0,
        "effective_from": "2026-01-01",
        # effective_to omitted => open-ended (PRD §3.1: null means open-ended)
    }
    defaults.update(overrides)
    return defaults


def create_accounting_period_payload(**overrides) -> dict:
    defaults = dict(PERIOD_2026_08)
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "order_type": "CAPITAL",
        "title": "Test work order",
        "initial_estimated_cost_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(**overrides) -> dict:
    defaults = {
        "estimated_cost_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def create_cost_charge_payload(**overrides) -> dict:
    defaults = {
        "cost_type": "MATERIAL",
        "base_amount_cents": 10_000,
        "charge_date": "2026-08-10",
    }
    defaults.update(overrides)
    return defaults


def create_ciac_agreement_payload(**overrides) -> dict:
    defaults = {
        "pledged_cents": 50_000,
        "pledge_expiry_at": CIAC_FAR_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_asset_payload(**overrides) -> dict:
    defaults = {
        "description": "Test deferral",
        "original_cents": 10_000,
        "amortization_months": 3,
    }
    defaults.update(overrides)
    return defaults


def make_unitization_line(unit_catalog_id, quantity) -> dict:
    """One closeout unitization line (PRD §3.8)."""
    return {"unit_catalog_id": unit_catalog_id, "quantity": quantity}
