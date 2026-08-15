"""Payload factories — one per entity, input fields only (PRD §3).

Business identifiers (segment_code, loan_number) must be globally unique
(PRD §3.2/§3.3), so defaults carry a random suffix.
"""
import uuid

from .constants import TEST_DEFAULTS


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def create_loss_model_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["MODEL_NAME"],
        "method": "LOSS_RATE",
        "forecast_period_quarters": TEST_DEFAULTS["FORECAST_PERIOD_QUARTERS"],
        "reversion_method": TEST_DEFAULTS["REVERSION_METHOD"],
        "reversion_period_quarters": TEST_DEFAULTS["REVERSION_PERIOD_QUARTERS"],
        "historical_lookback_quarters": TEST_DEFAULTS["HISTORICAL_LOOKBACK_QUARTERS"],
    }
    defaults.update(overrides)
    return defaults


def create_segment_payload(**overrides) -> dict:
    defaults = {
        "segment_code": _unique("SEG"),
        "name": "Prime Cards",
        "product_type": "CREDIT_CARD",
        "risk_rating_band": "PRIME",
        "vintage_year": 2024,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(segment_id: str, **overrides) -> dict:
    defaults = {
        "segment_id": segment_id,
        "loan_number": _unique("LN"),
        "amortized_cost_cents": 50_000,
        "risk_rating": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_scenario_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("SCN"),
        "scenario_type": "BASELINE",
        "unemployment_rate_bps": TEST_DEFAULTS["BASELINE_UNEMPLOYMENT_BPS"],
        "gdp_growth_bps": TEST_DEFAULTS["BASELINE_GDP_GROWTH_BPS"],
        "effective_from_period": TEST_DEFAULTS["WINDOW_FROM"],
        "effective_to_period": TEST_DEFAULTS["WINDOW_TO"],
    }
    defaults.update(overrides)
    return defaults


def adverse_scenario_payload(**overrides) -> dict:
    defaults = create_scenario_payload(
        scenario_type="ADVERSE",
        unemployment_rate_bps=TEST_DEFAULTS["ADVERSE_UNEMPLOYMENT_BPS"],
        gdp_growth_bps=TEST_DEFAULTS["ADVERSE_GDP_GROWTH_BPS"],
    )
    defaults.update(overrides)
    return defaults


def create_factor_payload(segment_id: str, **overrides) -> dict:
    defaults = {
        "segment_id": segment_id,
        "factor_code": "CONCENTRATION_RISK",
        "adjustment_bps": 25,
        "effective_from_period": "2026-Q1",
        "effective_to_period": "2026-Q2",
    }
    defaults.update(overrides)
    return defaults


def create_model_run_payload(loss_model_id: str, scenario_weights: list, **overrides) -> dict:
    defaults = {
        "as_of_period": TEST_DEFAULTS["AS_OF_PERIOD"],
        "loss_model_id": loss_model_id,
        "scenario_weights": scenario_weights,
    }
    defaults.update(overrides)
    return defaults


def charge_off_payload(amount_cents: int, **overrides) -> dict:
    defaults = {
        "charge_off_amount_cents": amount_cents,
        "charge_off_period": "2026-Q1",
    }
    defaults.update(overrides)
    return defaults


def recovery_payload(amount_cents: int, **overrides) -> dict:
    defaults = {
        "recovery_amount_cents": amount_cents,
        "recovery_period": "2026-Q2",
    }
    defaults.update(overrides)
    return defaults


def backtest_payload(**overrides) -> dict:
    defaults = {
        "backtest_period": "2026-Q1",
        "actual_loss_rate_bps": 300,
    }
    defaults.update(overrides)
    return defaults


def finalize_payload(**overrides) -> dict:
    defaults = {
        "period_charge_offs_cents": 0,
        "period_recoveries_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(amount_cents: int, expected_model_run_version: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "rationale": "Overlay for hurricane exposure in coastal counties",
        "expected_model_run_version": expected_model_run_version,
    }
    defaults.update(overrides)
    return defaults
