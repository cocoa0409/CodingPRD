"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from typing import List, Optional


def create_book_payload(
    name: str = "Book A",
    base_curve_rate_bps: int = 400,
    min_hedged_notional_cents: Optional[int] = None,
) -> dict:
    payload = {"name": name, "base_curve_rate_bps": base_curve_rate_bps}
    if min_hedged_notional_cents is not None:
        payload["min_hedged_notional_cents"] = min_hedged_notional_cents
    return payload


def create_position_payload(
    category: str,
    balance_cents: int,
    rate_bps: int,
    scheduled_runoff_pct: float,
    duration_years: float,
    deposit_segment: Optional[str] = None,
    is_prepayment_eligible: Optional[bool] = None,
) -> dict:
    payload = {
        "category": category,
        "balance_cents": balance_cents,
        "rate_bps": rate_bps,
        "scheduled_runoff_pct": scheduled_runoff_pct,
        "duration_years": duration_years,
    }
    if deposit_segment is not None:
        payload["deposit_segment"] = deposit_segment
    if is_prepayment_eligible is not None:
        payload["is_prepayment_eligible"] = is_prepayment_eligible
    return payload


def prepayment_params(base_cpr_pct: float = 10.0,
                      prepay_sensitivity_per_100bps: float = 2.0) -> dict:
    return {
        "base_cpr_pct": base_cpr_pct,
        "prepay_sensitivity_per_100bps": prepay_sensitivity_per_100bps,
    }


def deposit_decay_params(base_annual_decay_pct: float = 5.0,
                         surge_decay_per_100bps: float = 1.0) -> dict:
    return {
        "base_annual_decay_pct": base_annual_decay_pct,
        "surge_decay_per_100bps": surge_decay_per_100bps,
    }


def deposit_beta_params(up_beta_pct: float = 40.0,
                        down_beta_pct: float = 20.0,
                        lag_months: int = 6) -> dict:
    return {
        "up_beta_pct": up_beta_pct,
        "down_beta_pct": down_beta_pct,
        "lag_months": lag_months,
    }


def create_assumption_set_payload(domain: str, params: dict) -> dict:
    return {"domain": domain, "params": params}


def create_scenario_payload(
    name: str,
    kind: str,
    shock_bps: Optional[int] = None,
    ramp_total_bps: Optional[int] = None,
    ramp_months: Optional[int] = None,
    preset_code: Optional[str] = None,
    horizon_months: Optional[int] = None,
) -> dict:
    payload = {"name": name, "kind": kind}
    if shock_bps is not None:
        payload["shock_bps"] = shock_bps
    if ramp_total_bps is not None:
        payload["ramp_total_bps"] = ramp_total_bps
    if ramp_months is not None:
        payload["ramp_months"] = ramp_months
    if preset_code is not None:
        payload["preset_code"] = preset_code
    if horizon_months is not None:
        payload["horizon_months"] = horizon_months
    return payload


def create_simulation_run_payload(
    scenario_id: str,
    prepayment_set_id: str,
    decay_set_id: str,
    beta_set_id: str,
    balance_sheet_convention: str,
    expected_book_version: int,
    annual_growth_pct: Optional[float] = None,
) -> dict:
    payload = {
        "scenario_id": scenario_id,
        "prepayment_set_id": prepayment_set_id,
        "decay_set_id": decay_set_id,
        "beta_set_id": beta_set_id,
        "balance_sheet_convention": balance_sheet_convention,
        "expected_book_version": expected_book_version,
    }
    if annual_growth_pct is not None:
        payload["annual_growth_pct"] = annual_growth_pct
    return payload


def create_policy_limit_payload(metric: str,
                                applies_to_kinds: List[str],
                                threshold_pct: float) -> dict:
    return {
        "metric": metric,
        "applies_to_kinds": applies_to_kinds,
        "threshold_pct": threshold_pct,
    }


def create_hedge_payload(
    position_id: str,
    instrument: str = "PAYER_SWAP",
    designation_type: str = "FAIR_VALUE",
    notional_cents: int = 60_000_000,
    fixed_rate_bps: int = 350,
) -> dict:
    return {
        "position_id": position_id,
        "instrument": instrument,
        "designation_type": designation_type,
        "notional_cents": notional_cents,
        "fixed_rate_bps": fixed_rate_bps,
    }


def designate_hedge_payload(start_month: str,
                            end_month: str,
                            effectiveness_method: str) -> dict:
    return {
        "start_month": start_month,
        "end_month": end_month,
        "effectiveness_method": effectiveness_method,
    }


def effectiveness_test_payload(
    test_month: str,
    hedge_value_change_cents: int,
    hedged_item_value_change_cents: int,
    slope: Optional[float] = None,
    r_squared: Optional[float] = None,
    sample_count: Optional[int] = None,
) -> dict:
    payload = {
        "test_month": test_month,
        "hedge_value_change_cents": hedge_value_change_cents,
        "hedged_item_value_change_cents": hedged_item_value_change_cents,
    }
    if slope is not None:
        payload["slope"] = slope
    if r_squared is not None:
        payload["r_squared"] = r_squared
    if sample_count is not None:
        payload["sample_count"] = sample_count
    return payload


def create_backtest_payload(assumption_set_id: str,
                            start_month: str,
                            observation_months: int,
                            observed_value_pct: float) -> dict:
    return {
        "assumption_set_id": assumption_set_id,
        "start_month": start_month,
        "observation_months": observation_months,
        "observed_value_pct": observed_value_pct,
    }


def create_alco_report_payload(period_month: str = "2026-08") -> dict:
    return {"period_month": period_month}
