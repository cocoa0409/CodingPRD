"""Entity -> JSON projections. Decimal values are emitted as JSON numbers."""

from decimal import Decimal

import calc
import domain


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def policy(row):
    out = {
        "policy_code": row["policy_code"],
        "fiscal_year": row["fiscal_year"],
        "max_coverage_pct": num(row["max_coverage_pct"]),
        "min_coverage_pct": num(row["min_coverage_pct"]),
        "max_single_counterparty_pct": num(row["max_single_counterparty_pct"]),
        "permitted_instrument_types": list(row["permitted_instrument_types"]),
        "max_earnings_volatility_usd": num(row["max_earnings_volatility_usd"]),
        "max_tankering_uplift_gallons": num(row["max_tankering_uplift_gallons"]),
        "min_days_cover": num(row["min_days_cover"]),
        "eligible_fleet_types": list(row["eligible_fleet_types"]),
        "status": row["status"],
        "open_exception_count": domain.open_exception_count(row),
    }
    out.update(_common(row))
    return out


def counterparty(row):
    utilized, posted, open_calls, pct, posture = domain.counterparty_ledgers(row)
    out = {
        "counterparty_code": row["counterparty_code"],
        "legal_name": row["legal_name"],
        "credit_rating": row["credit_rating"],
        "credit_limit_usd": num(row["credit_limit_usd"]),
        "status": row["status"],
        "utilized_credit_usd": num(utilized),
        "posted_collateral_usd": num(posted),
        "utilization_pct": num(pct),
        "credit_posture": posture,
        "open_margin_call_count": open_calls,
        "last_review_note": row["last_review_note"],
    }
    out.update(_common(row))
    return out


def station(row):
    effective, days, posture = domain.station_derived(row)
    out = {
        "iata_code": row["iata_code"],
        "name": row["name"],
        "into_plane_fee_usd_per_gal": num(row["into_plane_fee_usd_per_gal"]),
        "consortium_member": row["consortium_member"],
        "consortium_share_pct": num(row["consortium_share_pct"]),
        "consortium_pool_gallons": num(row["consortium_pool_gallons"]),
        "avg_daily_liftings_gallons": num(row["avg_daily_liftings_gallons"]),
        "inventory_gallons": num(row["inventory_gallons"]),
        "effective_inventory_gallons": num(effective),
        "days_cover": num(days),
        "supply_posture": posture,
    }
    out.update(_common(row))
    return out


def contract(row):
    out = {
        "station_id": row["station_id"],
        "contract_ref": row["contract_ref"],
        "index_basis": row["index_basis"],
        "index_price_usd_per_gal": num(row["index_price_usd_per_gal"]),
        "differential_usd_per_gal": num(row["differential_usd_per_gal"]),
        "term_start_date": row["term_start_date"],
        "term_end_date": row["term_end_date"],
        "min_monthly_gallons": num(row["min_monthly_gallons"]),
        "max_monthly_gallons": num(row["max_monthly_gallons"]),
        "status": domain.contract_status(row),
        "all_in_price_usd_per_gal": num(domain.contract_all_in_price(row)),
    }
    out.update(_common(row))
    return out


def forecast(row):
    out = {
        "fleet_type": row["fleet_type"],
        "route_group": row["route_group"],
        "season": row["season"],
        "period_start_month": row["period_start_month"],
        "period_end_month": row["period_end_month"],
        "forecast_gallons": num(row["forecast_gallons"]),
        "status": row["status"],
        "published_at": row["published_at"],
    }
    out.update(_common(row))
    return out


def program(row):
    cov = domain.program_coverage(row)
    out = {
        "policy_id": row["policy_id"],
        "program_code": row["program_code"],
        "period_start_month": row["period_start_month"],
        "period_end_month": row["period_end_month"],
        "route_groups": list(row["route_groups"]),
        "target_coverage_pct": num(row["target_coverage_pct"]),
        "consumption_basis_gallons": num(row["consumption_basis_gallons"]),
        "hedged_gallons": num(cov["hedged_gallons"]),
        "delta_adjusted_gallons": num(cov["delta_adjusted_gallons"]),
        "coverage_pct_notional": num(cov["coverage_pct_notional"]),
        "coverage_pct_delta": num(cov["coverage_pct_delta"]),
        "planned_coverage_pct_delta": num(cov["planned_coverage_pct_delta"]),
        "designated_mtm_usd": num(row["designated_mtm_usd"]),
        "undesignated_mtm_usd": num(row["undesignated_mtm_usd"]),
        "earnings_volatility_usd": num(calc.r2(abs(row["undesignated_mtm_usd"]))),
        "compliance_posture": row["compliance_posture"],
        "open_instrument_count": cov["open_instrument_count"],
        "status": row["status"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "return_count": row["return_count"],
    }
    out.update(_common(row))
    return out


def instrument(row):
    out = {
        "hedge_program_id": row["hedge_program_id"],
        "counterparty_id": row["counterparty_id"],
        "instrument_type": row["instrument_type"],
        "notional_gallons": num(row["notional_gallons"]),
        "strike_usd_per_gal": num(row["strike_usd_per_gal"]),
        "cap_strike_usd_per_gal": num(row["cap_strike_usd_per_gal"]),
        "floor_strike_usd_per_gal": num(row["floor_strike_usd_per_gal"]),
        "premium_usd": num(row["premium_usd"]),
        "maturity_month": row["maturity_month"],
        "trade_status": row["trade_status"],
        "accounting_status": row["accounting_status"],
        "delta_factor": num(row["delta_factor"]),
        "delta_adjusted_gallons": num(row["delta_adjusted_gallons"]),
        "mtm_value_usd": num(row["mtm_value_usd"]),
        "margin_requirement_usd": num(row["margin_requirement_usd"]),
        "collateral_posted_usd": num(domain.instrument_collateral_posted(row)),
        "cumulative_hedge_change_usd": num(row["cumulative_hedge_change_usd"]),
        "cumulative_item_change_usd": num(row["cumulative_item_change_usd"]),
        "proposed_by_user_id": row["proposed_by_user_id"],
        "executed_at": row["executed_at"],
        "designated_at": row["designated_at"],
    }
    out.update(_common(row))
    return out


def posting(row):
    out = {
        "counterparty_id": row["counterparty_id"],
        "hedge_instrument_id": row["hedge_instrument_id"],
        "collateral_type": row["collateral_type"],
        "required_amount_usd": num(row["required_amount_usd"]),
        "posted_amount_usd": num(row["posted_amount_usd"]),
        "status": row["status"],
        "origin": row["origin"],
        "posted_at": row["posted_at"],
        "returned_at": row["returned_at"],
    }
    out.update(_common(row))
    return out


def effectiveness_test(row):
    out = {
        "hedge_instrument_id": row["hedge_instrument_id"],
        "period_month": row["period_month"],
        "hedge_change_usd": num(row["hedge_change_usd"]),
        "hedged_item_change_usd": num(row["hedged_item_change_usd"]),
        "period_ratio": num(row["period_ratio"]),
        "cumulative_ratio": num(row["cumulative_ratio"]),
        "result": row["result"],
        "tested_by_user_id": row["tested_by_user_id"],
    }
    out.update(_common(row, versioned=False))
    return out


def mtm_run(row):
    out = {
        "period_month": row["period_month"],
        "settlement_index_usd_per_gal": num(row["settlement_index_usd_per_gal"]),
        "status": row["status"],
        "instrument_count": row["instrument_count"],
        "total_mtm_usd": num(row["total_mtm_usd"]),
        "designated_mtm_usd": num(row["designated_mtm_usd"]),
        "undesignated_mtm_usd": num(row["undesignated_mtm_usd"]),
        "margin_calls_created": row["margin_calls_created"],
        "settled_instrument_count": row["settled_instrument_count"],
        "computed_at": row["computed_at"],
        "published_at": row["published_at"],
    }
    out.update(_common(row))
    return out


def flight_leg(row):
    out = {
        "flight_number": row["flight_number"],
        "departure_date": row["departure_date"],
        "origin_station_id": row["origin_station_id"],
        "destination_station_id": row["destination_station_id"],
        "fleet_type": row["fleet_type"],
        "planned_block_minutes": row["planned_block_minutes"],
        "planned_burn_gallons": num(row["planned_burn_gallons"]),
        "tank_capacity_gallons": num(row["tank_capacity_gallons"]),
        "payload_lbs": num(row["payload_lbs"]),
        "max_takeoff_payload_lbs": num(row["max_takeoff_payload_lbs"]),
        "landing_weight_lbs": num(row["landing_weight_lbs"]),
        "max_landing_weight_lbs": num(row["max_landing_weight_lbs"]),
        "uplift_cap_gallons": num(domain.leg_uplift_cap(row)),
        "actual_block_minutes": row["actual_block_minutes"],
        "actual_uplift_gallons": num(row["actual_uplift_gallons"]),
    }
    out.update(_common(row))
    return out


def directive(row):
    out = {
        "flight_leg_id": row["flight_leg_id"],
        "requested_uplift_gallons": num(row["requested_uplift_gallons"]),
        "status": row["status"],
        "planned_burn_penalty_gallons": num(row["planned_burn_penalty_gallons"]),
        "planned_gross_savings_usd": num(row["planned_gross_savings_usd"]),
        "planned_penalty_cost_usd": num(row["planned_penalty_cost_usd"]),
        "planned_net_savings_usd": num(row["planned_net_savings_usd"]),
        "pinned_origin_price_usd_per_gal": num(row["pinned_origin_price_usd_per_gal"]),
        "pinned_destination_price_usd_per_gal": num(row["pinned_destination_price_usd_per_gal"]),
        "pinned_origin_contract_ref": row["pinned_origin_contract_ref"],
        "reconciled_burn_penalty_gallons": num(row["reconciled_burn_penalty_gallons"]),
        "reconciled_net_savings_usd": num(row["reconciled_net_savings_usd"]),
        "savings_variance_usd": num(row["savings_variance_usd"]),
        "revision_count": row["revision_count"],
        "proposed_by_user_id": row["proposed_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
    }
    out.update(_common(row))
    return out


def exception(row):
    out = {
        "reason_code": row["reason_code"],
        "hedge_program_id": row["hedge_program_id"],
        "hedge_instrument_id": row["hedge_instrument_id"],
        "tankering_directive_id": row["tankering_directive_id"],
        "justification": row["justification"],
        "requested_limit_value": num(row["requested_limit_value"]),
        "status": row["status"],
        "origin": row["origin"],
        "requested_by_user_id": row["requested_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": row["decided_at"],
    }
    out.update(_common(row))
    return out
