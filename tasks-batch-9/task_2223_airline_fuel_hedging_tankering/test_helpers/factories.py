"""Request-payload builders.

Each builder returns a complete, valid body for one write endpoint and accepts
``**overrides`` so a test can perturb exactly the field under examination and
leave everything else at a known-good baseline. Field names are the PRD's.

The baselines are deliberately shared: a policy at a 60.00 coverage ceiling and
a 15.00 floor, a station at a 0.0450 into-plane fee lifting 100,000 gallons a
day, a 4,000,000-gallon SUMMER forecast, and a narrowbody leg with a 10,600.00
gallon uplift cap. Tests that need different numbers say so explicitly.
"""

from typing import Any, Dict, Optional

# ─── Hedging policy (PRD §3.1) ────────────────────────

def hedge_policy_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "policy_code": "FY27-BASE",
        "fiscal_year": 2027,
        "max_coverage_pct": 60.00,
        "min_coverage_pct": 15.00,
        "max_single_counterparty_pct": 45.00,
        "max_earnings_volatility_usd": 150000.00,
        "max_tankering_uplift_gallons": 12000,
        "min_days_cover": 3.00,
        "permitted_instrument_types": ["SWAP", "COLLAR", "CALL_OPTION"],
        "eligible_fleet_types": ["NARROWBODY", "WIDEBODY", "REGIONAL"],
    }
    payload.update(overrides)
    return payload


# ─── Counterparty and credit review (PRD §3.1) ────────

def counterparty_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "counterparty_code": "CP-ALPHA",
        "legal_name": "Gulf Coast Commodity Swaps LLC",
        "credit_rating": "AA",
        "credit_limit_usd": 2000000.00,
    }
    payload.update(overrides)
    return payload


def credit_review_payload(
    credit_rating: str,
    review_note: str = "Annual review completed.",
    credit_limit_usd: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "credit_rating": credit_rating,
        "review_note": review_note,
    }
    if credit_limit_usd is not None:
        payload["credit_limit_usd"] = credit_limit_usd
    return payload


# ─── Stations, contracts and inventory (PRD §3.2) ─────

def station_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "iata_code": "ORD",
        "name": "Chicago O'Hare",
        "into_plane_fee_usd_per_gal": 0.0450,
        "avg_daily_liftings_gallons": 100000,
    }
    payload.update(overrides)
    return payload


def origin_station_payload(**overrides: Any) -> Dict[str, Any]:
    """The cheap uplift station used by every tankering scenario."""
    return station_payload(
        iata_code="ORD",
        name="Chicago O'Hare",
        into_plane_fee_usd_per_gal=0.0450,
        avg_daily_liftings_gallons=100000,
        **overrides,
    )


def destination_station_payload(**overrides: Any) -> Dict[str, Any]:
    """The expensive arrival station the saving is measured against."""
    return station_payload(
        iata_code="DFW",
        name="Dallas Fort Worth",
        into_plane_fee_usd_per_gal=0.0800,
        avg_daily_liftings_gallons=100000,
        **overrides,
    )


def supply_contract_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "contract_ref": "ORD-2027-A",
        "index_basis": "PLATTS_USGC",
        "index_price_usd_per_gal": 2.4000,
        "differential_usd_per_gal": 0.0250,
        "term_start_date": "2027-01-01",
        "term_end_date": "2027-06-30",
        "min_monthly_gallons": 0,
        "max_monthly_gallons": 5000000,
    }
    payload.update(overrides)
    return payload


def destination_contract_payload(**overrides: Any) -> Dict[str, Any]:
    """2.9000 index plus a 0.1200 differential over a 0.0800 into-plane fee."""
    return supply_contract_payload(
        contract_ref="DFW-2027-A",
        index_price_usd_per_gal=2.9000,
        differential_usd_per_gal=0.1200,
        **overrides,
    )


def inventory_adjustment_payload(
    delta_gallons: float,
    reason: str = "Barge delivery received.",
    consortium_pool_gallons: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delta_gallons": delta_gallons,
        "reason": reason,
    }
    if consortium_pool_gallons is not None:
        payload["consortium_pool_gallons"] = consortium_pool_gallons
    return payload


# ─── Consumption forecasts (PRD §3.3) ─────────────────

def consumption_forecast_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "fleet_type": "NARROWBODY",
        "route_group": "DOMESTIC_SHORT",
        "season": "SUMMER",
        "period_start_month": "2027-01",
        "period_end_month": "2027-04",
        "forecast_gallons": 4000000,
    }
    payload.update(overrides)
    return payload


# ─── Hedge programmes (PRD §3.3) ──────────────────────

def hedge_program_payload(policy_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "policy_id": policy_id,
        "program_code": "HP-BASE",
        "period_start_month": "2027-01",
        "period_end_month": "2027-03",
        "route_groups": ["DOMESTIC_SHORT", "TRANSATLANTIC"],
        "target_coverage_pct": 40.00,
    }
    payload.update(overrides)
    return payload


def return_program_payload(
    return_note: str = "Rework the counterparty split before approval.",
) -> Dict[str, Any]:
    return {"return_note": return_note}


# ─── Hedge instruments (PRD §3.4) ─────────────────────

def swap_payload(
    counterparty_id: str,
    expected_hedge_program_version: int,
    notional_gallons: float = 2000000,
    strike_usd_per_gal: float = 2.4000,
    maturity_month: str = "2027-02",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "counterparty_id": counterparty_id,
        "instrument_type": "SWAP",
        "notional_gallons": notional_gallons,
        "maturity_month": maturity_month,
        "strike_usd_per_gal": strike_usd_per_gal,
        "expected_hedge_program_version": expected_hedge_program_version,
    }
    payload.update(overrides)
    return payload


def collar_payload(
    counterparty_id: str,
    expected_hedge_program_version: int,
    notional_gallons: float = 2000000,
    floor_strike_usd_per_gal: float = 2.1000,
    cap_strike_usd_per_gal: float = 2.7000,
    maturity_month: str = "2027-02",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "counterparty_id": counterparty_id,
        "instrument_type": "COLLAR",
        "notional_gallons": notional_gallons,
        "maturity_month": maturity_month,
        "floor_strike_usd_per_gal": floor_strike_usd_per_gal,
        "cap_strike_usd_per_gal": cap_strike_usd_per_gal,
        "expected_hedge_program_version": expected_hedge_program_version,
    }
    payload.update(overrides)
    return payload


def call_option_payload(
    counterparty_id: str,
    expected_hedge_program_version: int,
    notional_gallons: float = 1000000,
    strike_usd_per_gal: float = 2.6000,
    premium_usd: float = 120000.00,
    maturity_month: str = "2027-02",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "counterparty_id": counterparty_id,
        "instrument_type": "CALL_OPTION",
        "notional_gallons": notional_gallons,
        "maturity_month": maturity_month,
        "strike_usd_per_gal": strike_usd_per_gal,
        "premium_usd": premium_usd,
        "expected_hedge_program_version": expected_hedge_program_version,
    }
    payload.update(overrides)
    return payload


def terminate_payload(
    termination_reason: str = "Unwound at the desk's request.",
) -> Dict[str, Any]:
    return {"termination_reason": termination_reason}


# ─── Collateral (PRD §3.5) ────────────────────────────

def collateral_posting_payload(
    hedge_instrument_id: str,
    expected_counterparty_version: int,
    collateral_type: str = "CASH",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "hedge_instrument_id": hedge_instrument_id,
        "collateral_type": collateral_type,
        "expected_counterparty_version": expected_counterparty_version,
    }
    payload.update(overrides)
    return payload


def post_collateral_payload(amount_usd: float) -> Dict[str, Any]:
    return {"amount_usd": amount_usd}


def return_collateral_payload(
    return_reason: str = "Trade closed out; collateral surplus to requirement.",
) -> Dict[str, Any]:
    return {"return_reason": return_reason}


# ─── Hedge accounting (PRD §3.6) ──────────────────────

def effectiveness_test_payload(
    period_month: str,
    hedge_change_usd: float,
    hedged_item_change_usd: float,
) -> Dict[str, Any]:
    return {
        "period_month": period_month,
        "hedge_change_usd": hedge_change_usd,
        "hedged_item_change_usd": hedged_item_change_usd,
    }


# ─── Mark-to-market runs (PRD §3.7) ───────────────────

def mtm_run_payload(
    period_month: str = "2027-02",
    settlement_index_usd_per_gal: float = 2.5000,
) -> Dict[str, Any]:
    return {
        "period_month": period_month,
        "settlement_index_usd_per_gal": settlement_index_usd_per_gal,
    }


# ─── Tankering (PRD §3.8) ─────────────────────────────

def flight_leg_payload(
    origin_station_id: str,
    destination_station_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Narrowbody baseline: tank headroom 10,600 is the binding uplift cap term."""
    payload = {
        "flight_number": "UA100",
        "departure_date": "2027-02-15",
        "origin_station_id": origin_station_id,
        "destination_station_id": destination_station_id,
        "fleet_type": "NARROWBODY",
        "planned_block_minutes": 210,
        "planned_burn_gallons": 14500,
        "tank_capacity_gallons": 26000,
        "payload_lbs": 22000,
        "max_takeoff_payload_lbs": 45000,
        "landing_weight_lbs": 128000,
        "max_landing_weight_lbs": 200000,
    }
    payload.update(overrides)
    return payload


def tankering_directive_payload(
    requested_uplift_gallons: float,
    expected_flight_leg_version: int,
) -> Dict[str, Any]:
    return {
        "requested_uplift_gallons": requested_uplift_gallons,
        "expected_flight_leg_version": expected_flight_leg_version,
    }


def reject_directive_payload(
    reject_reason: str = "Network planning withdrew the tankering request.",
) -> Dict[str, Any]:
    return {"reject_reason": reject_reason}


def request_revision_payload(
    revision_note: str = "Trim the uplift and re-price against today's contracts.",
) -> Dict[str, Any]:
    return {"revision_note": revision_note}


def revise_directive_payload(requested_uplift_gallons: float) -> Dict[str, Any]:
    return {"requested_uplift_gallons": requested_uplift_gallons}


def reconcile_directive_payload(
    actual_uplift_gallons: float,
    actual_block_minutes: int,
) -> Dict[str, Any]:
    return {
        "actual_uplift_gallons": actual_uplift_gallons,
        "actual_block_minutes": actual_block_minutes,
    }


# ─── Policy exceptions (PRD §3.9) ─────────────────────

def policy_exception_payload(
    reason_code: str,
    justification: str = "Board-approved tolerance for this fiscal quarter only.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason_code": reason_code,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


def decision_payload(
    decision_note: str = "Reviewed with treasury; tolerance granted.",
) -> Dict[str, Any]:
    return {"decision_note": decision_note}
