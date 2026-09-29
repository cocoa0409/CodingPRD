"""Entity -> JSON projections. Computed fields are derived at read time."""

from db import store
from services import calc, derive
from util import fmt_ts, num


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def mine_json(mine):
    out = _common(mine)
    out.update({
        "name": mine["name"],
        "state_code": mine["state_code"],
        "rated_hoist_tons_per_day": num(mine["rated_hoist_tons_per_day"]),
        "ground_control_plan_version": mine["ground_control_plan_version"],
        "hoist_state": mine["hoist_state"],
        "compliance_state": mine["compliance_state"],
        "effective_hoist_tons_per_day": num(mine["effective_hoist_tons_per_day"]),
        "scheduled_hoist_tons_open": num(
            derive.mine_scheduled_hoist_tons_open(mine["id"])),
        "producing_panel_count": derive.mine_producing_panel_count(mine["id"]),
        "last_compliance_action_at": fmt_ts(mine.get("last_compliance_action_at")),
    })
    return out


def panel_json(panel):
    out = _common(panel)
    out.update({
        "mine_id": panel["mine_id"],
        "panel_code": panel["panel_code"],
        "gross_tons_in_place": num(panel["gross_tons_in_place"]),
        "extraction_ratio_pct": num(panel["extraction_ratio_pct"]),
        "grade_pct_nacl": num(panel["grade_pct_nacl"]),
        "insolubles_pct": num(panel["insolubles_pct"]),
        "pillar_recovery_allowed": panel["pillar_recovery_allowed"],
        "recoverable_tons": num(panel["recoverable_tons"]),
        "mined_tons": num(derive.panel_mined_tons(panel["id"])),
        "status": panel["status"],
        "ground_control_defect_count": derive.panel_defect_count(panel["id"]),
        "open_defect": panel["open_defect"],
        "suspended_by_user_id": panel.get("suspended_by_user_id"),
    })
    return out


def inspection_json(inspection):
    return {
        "id": inspection["id"],
        "created_at": fmt_ts(inspection["created_at"]),
        "panel_id": inspection["panel_id"],
        "roof_span_ft": num(inspection["roof_span_ft"]),
        "convergence_rate_in_per_day": num(inspection["convergence_rate_in_per_day"]),
        "finding": inspection["finding"],
        "inspector_user_id": inspection["inspector_user_id"],
        "caused_suspension": inspection["caused_suspension"],
    }


def run_json(run):
    out = _common(run)
    out.update({
        "mine_id": run["mine_id"],
        "panel_id": run["panel_id"],
        "planned_tons": num(run["planned_tons"]),
        "hoist_window_start": fmt_ts(run["hoist_window_start"]),
        "hoist_window_end": fmt_ts(run["hoist_window_end"]),
        "planned_tons_per_hour": num(run["planned_tons_per_hour"]),
        "hoisted_tons": num(run["hoisted_tons"]),
        "status": run["status"],
        "held_reason": run.get("held_reason"),
        "open_batch_count": derive.run_open_batch_count(run["id"]),
    })
    return out


def batch_json(batch):
    out = _common(batch)
    out.update({
        "production_run_id": batch["production_run_id"],
        "depot_id": batch["depot_id"],
        "product_line": batch["product_line"],
        "screen_spec": batch["screen_spec"],
        "anticaking_ppm": num(batch["anticaking_ppm"]),
        "corrosion_inhibitor_pct": num(batch["corrosion_inhibitor_pct"]),
        "input_tons": num(batch["input_tons"]),
        "moisture_pct": num(batch["moisture_pct"]),
        "storage_kind": batch["storage_kind"],
        "yield_tons": num(batch["yield_tons"]),
        "purity_pct_nacl": num(batch["purity_pct_nacl"]),
        "qc_state": batch["qc_state"],
        "rework_count": batch["rework_count"],
        "created_by_user_id": batch["created_by_user_id"],
        "qc_decided_by_user_id": batch.get("qc_decided_by_user_id"),
    })
    return out


def depot_json(depot):
    out = _common(depot)
    out.update({
        "name": depot["name"],
        "state_code": depot["state_code"],
        "covered_capacity_tons": num(depot["covered_capacity_tons"]),
        "open_pad_capacity_tons": num(depot["open_pad_capacity_tons"]),
        "loadout_rate_tons_per_hour": num(depot["loadout_rate_tons_per_hour"]),
        "outbound_freight_rate_per_ton": num(depot["outbound_freight_rate_per_ton"]),
        "depot_state": depot["depot_state"],
        "covered_stored_tons": num(derive.depot_covered_stored(depot["id"])),
        "open_pad_stored_tons": num(derive.depot_open_pad_stored(depot["id"])),
        "covered_utilization_pct": num(derive.depot_utilization_pct(depot)),
        "storm_state_set_by_user_id": depot.get("storm_state_set_by_user_id"),
    })
    return out


def lot_json(lot):
    out = _common(lot)
    out.update({
        "depot_id": lot["depot_id"],
        "treatment_batch_id": lot["treatment_batch_id"],
        "product_line": lot["product_line"],
        "purity_pct_nacl": num(lot["purity_pct_nacl"]),
        "storage_kind": lot["storage_kind"],
        "tons_on_hand": num(lot["tons_on_hand"]),
        "tons_reserved": num(derive.lot_reserved_tons(lot["id"])),
        "tons_available": num(derive.lot_available_tons(lot)),
        "lot_state": lot["lot_state"],
        "quarantine_reason": lot.get("quarantine_reason"),
    })
    return out


def shipment_json(shipment):
    out = _common(shipment)
    out.update({
        "stockpile_lot_id": shipment["stockpile_lot_id"],
        "origin_depot_id": shipment["origin_depot_id"],
        "destination_depot_id": shipment["destination_depot_id"],
        "mode": shipment["mode"],
        "tons": num(shipment["tons"]),
        "load_window_start": fmt_ts(shipment["load_window_start"]),
        "load_window_end": fmt_ts(shipment["load_window_end"]),
        "destination_storage_kind": shipment["destination_storage_kind"],
        "required_gap_minutes": shipment["required_gap_minutes"],
        "status": shipment["status"],
        "received_lot_id": shipment.get("received_lot_id"),
    })
    return out


def forecast_json(forecast):
    out = _common(forecast)
    out.update({
        "season_code": forecast["season_code"],
        "region_code": forecast["region_code"],
        "normal_season_tons": num(forecast["normal_season_tons"]),
        "severity_index": forecast["severity_index"],
        "prior_season_1_actual_tons": num(forecast["prior_season_1_actual_tons"]),
        "prior_season_2_actual_tons": num(forecast["prior_season_2_actual_tons"]),
        "prior_season_3_actual_tons": num(forecast["prior_season_3_actual_tons"]),
        "method": forecast["method"],
        "preseason_lock_date": fmt_ts(forecast["preseason_lock_date"]),
        "target_tons_severity_weighted": num(forecast["target_tons_severity_weighted"]),
        "target_tons_trailing_baseline": num(forecast["target_tons_trailing_baseline"]),
        "binding_target_tons": num(forecast["binding_target_tons"]),
        "variant_spread_tons": num(forecast["variant_spread_tons"]),
    })
    return out


def contract_json(contract):
    fulfilled = derive.contract_fulfilled_tons(contract["id"])
    accrued = derive.contract_penalty_accrued(contract["id"])
    out = _common(contract)
    out.update({
        "season_forecast_id": contract["season_forecast_id"],
        "customer_name": contract["customer_name"],
        "jurisdiction_level": contract["jurisdiction_level"],
        "state_code": contract["state_code"],
        "product_line": contract["product_line"],
        "committed_tons": num(contract["committed_tons"]),
        "guaranteed_price_per_ton": num(contract["guaranteed_price_per_ton"]),
        "min_take_pct": num(contract["min_take_pct"]),
        "max_take_pct": num(contract["max_take_pct"]),
        "failure_to_supply_penalty_per_ton": num(
            contract["failure_to_supply_penalty_per_ton"]),
        "price_guarantee_cap_pct": num(contract["price_guarantee_cap_pct"]),
        "status": contract["status"],
        "submitted_by_user_id": contract.get("submitted_by_user_id"),
        "decided_by_user_id": contract.get("decided_by_user_id"),
        "contract_value_usd": num(contract.get("contract_value_usd")),
        "fulfilled_tons": num(fulfilled),
        "open_committed_tons": num(
            derive.contract_open_committed_tons(contract, fulfilled)),
        "take_pct": num(derive.contract_take_pct(contract, fulfilled)),
        "penalty_accrued_usd": num(accrued),
        "season_penalty_usd": num(contract.get("season_penalty_usd")),
        "penalty_reconciliation_delta_usd": num(
            contract.get("penalty_reconciliation_delta_usd")),
        "supply_reliability_score": num(derive.contract_supply_reliability(contract)),
        "breach_watch": derive.contract_breach_watch(contract, accrued),
    })
    return out


def order_json(order):
    out = _common(order)
    out.update({
        "bid_contract_id": order["bid_contract_id"],
        "depot_id": order["depot_id"],
        "requested_tons": num(order["requested_tons"]),
        "required_by": fmt_ts(order["required_by"]),
        "storm_priority": order["storm_priority"],
        "allocated_tons": num(derive.order_allocated_tons(order["id"])),
        "shorted_tons": num(order["shorted_tons"]),
        "status": order["status"],
        "penalty_state": order["penalty_state"],
        "shortfall_penalty_usd": num(order["shortfall_penalty_usd"]),
        "market_index_price_per_ton": num(order["market_index_price_per_ton"]),
        "product_subtotal_usd": num(order.get("product_subtotal_usd")),
        "freight_subtotal_usd": num(order.get("freight_subtotal_usd")),
        "storm_surcharge_usd": num(order.get("storm_surcharge_usd")),
        "guarantee_credit_usd": num(order.get("guarantee_credit_usd")),
        "invoice_total_usd": num(order.get("invoice_total_usd")),
        "delivered_at": fmt_ts(order.get("delivered_at")),
    })
    return out


def allocation_json(alloc):
    out = _common(alloc)
    out.update({
        "delivery_order_id": alloc["delivery_order_id"],
        "stockpile_lot_id": alloc["stockpile_lot_id"],
        "tons": num(alloc["tons"]),
        "origin": alloc["origin"],
        "rank_position": alloc["rank_position"],
        "state": alloc["state"],
    })
    return out


# ------------------------------------------------------- computed read shapes

def hoist_capacity_json(mine):
    hoist_factor, compliance_factor = calc.mine_factors(mine)
    return {
        "mine_id": mine["id"],
        "rated_hoist_tons_per_day": num(mine["rated_hoist_tons_per_day"]),
        "hoist_factor": num(hoist_factor),
        "compliance_factor": num(compliance_factor),
        "effective_hoist_tons_per_day": num(mine["effective_hoist_tons_per_day"]),
        "mine_hourly_capacity": float(calc.mine_hourly_capacity(mine)),
        "scheduled_hoist_tons_open": num(
            derive.mine_scheduled_hoist_tons_open(mine["id"])),
        "scheduled_run_count": len(derive.scheduled_runs_of_mine(mine["id"])),
    }


def storage_posture_json(depot):
    return {
        "depot_id": depot["id"],
        "depot_state": depot["depot_state"],
        "covered_capacity_tons": num(depot["covered_capacity_tons"]),
        "covered_stored_tons": num(derive.depot_covered_stored(depot["id"])),
        "open_pad_capacity_tons": num(depot["open_pad_capacity_tons"]),
        "open_pad_stored_tons": num(derive.depot_open_pad_stored(depot["id"])),
        "covered_utilization_pct": num(derive.depot_utilization_pct(depot)),
        "auto_surge_threshold_pct": num(calc.AUTO_SURGE_THRESHOLD_PCT),
        "reserved_tons": num(derive.depot_reserved_tons(depot["id"])),
    }


def ledger_json(contract):
    fulfilled = derive.contract_fulfilled_tons(contract["id"])
    accrued = derive.contract_penalty_accrued(contract["id"])
    return {
        "bid_contract_id": contract["id"],
        "committed_tons": num(contract["committed_tons"]),
        "fulfilled_tons": num(fulfilled),
        "open_committed_tons": num(
            derive.contract_open_committed_tons(contract, fulfilled)),
        "take_pct": num(derive.contract_take_pct(contract, fulfilled)),
        "take_band_consumed_tons": num(
            derive.contract_take_band_consumed(contract["id"])),
        "take_band_limit_tons": num(derive.contract_take_band_limit(contract)),
        "penalty_accrued_usd": num(accrued),
        "accrued_penalty_order_count": derive.contract_accrued_order_count(
            contract["id"]),
        "supply_reliability_score": num(derive.contract_supply_reliability(contract)),
        "breach_watch": derive.contract_breach_watch(contract, accrued),
        "preseason_coverage_tons": num(derive.contract_preseason_coverage(contract)),
        "preseason_coverage_required_tons": num(
            derive.contract_preseason_required(contract)),
    }
