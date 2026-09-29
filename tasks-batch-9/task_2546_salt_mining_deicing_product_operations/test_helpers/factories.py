"""
Request-payload builders for the Salt Deicing Operations API.

Each builder produces a valid payload carrying exactly the fields the PRD marks
required for that endpoint, and adds an optional field only when the caller passes
it — so `optional inputs omitted` cases exercise the PRD's declared defaults rather
than a test-supplied value. Overrides are keyword arguments; `None` is a legal
override value and is passed through, which is how required-field-null cases are
built.
"""

from typing import Any, Dict, Optional

from .constants import (
    COARSE,
    COVERED,
    HIGHWAY_DEICING,
    JURISDICTION_MUNICIPAL,
    METHOD_SEVERITY_WEIGHTED,
    MODE_RAIL,
)

_UNSET = object()


def _put(payload: Dict[str, Any], key: str, value: Any) -> None:
    """Add `key` only when the caller actually supplied a value."""
    if value is not _UNSET:
        payload[key] = value


# ─── Mines (PRD §3.1) ─────────────────────────────────


def mine_payload(
    name: str = "Retsof Mine",
    state_code: str = "NY",
    rated_hoist_tons_per_day: float = 24000,
    ground_control_plan_version: Any = _UNSET,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "state_code": state_code,
        "rated_hoist_tons_per_day": rated_hoist_tons_per_day,
    }
    _put(payload, "ground_control_plan_version", ground_control_plan_version)
    return payload


def hoist_status_payload(hoist_state: str, note: Any = _UNSET) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"hoist_state": hoist_state}
    _put(payload, "note", note)
    return payload


def compliance_action_payload(
    action: str, inspection_id: Any = _UNSET, note: Any = _UNSET
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    _put(payload, "inspection_id", inspection_id)
    _put(payload, "note", note)
    return payload


# ─── Panels (PRD §3.2) ────────────────────────────────


def panel_payload(
    mine_id: str,
    panel_code: str = "P-1",
    gross_tons_in_place: float = 1000000,
    extraction_ratio_pct: float = 60,
    grade_pct_nacl: float = 95.0,
    insolubles_pct: float = 5.0,
    pillar_recovery_allowed: Any = _UNSET,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mine_id": mine_id,
        "panel_code": panel_code,
        "gross_tons_in_place": gross_tons_in_place,
        "extraction_ratio_pct": extraction_ratio_pct,
        "grade_pct_nacl": grade_pct_nacl,
        "insolubles_pct": insolubles_pct,
    }
    _put(payload, "pillar_recovery_allowed", pillar_recovery_allowed)
    return payload


def suspend_payload(reason: str = "Roof convergence above trigger") -> Dict[str, Any]:
    return {"reason": reason}


def remediate_payload(
    remediation_note: str = "Bolts and straps installed; convergence stable",
) -> Dict[str, Any]:
    return {"remediation_note": remediation_note}


def abandon_payload(reason: str = "Ground conditions unrecoverable") -> Dict[str, Any]:
    return {"reason": reason}


# ─── Ground-control inspections (PRD §3.3) ────────────


def inspection_payload(
    panel_id: str,
    finding: str,
    roof_span_ft: float = 30.0,
    convergence_rate_in_per_day: float = 0.125,
) -> Dict[str, Any]:
    return {
        "panel_id": panel_id,
        "roof_span_ft": roof_span_ft,
        "convergence_rate_in_per_day": convergence_rate_in_per_day,
        "finding": finding,
    }


# ─── Production runs (PRD §3.4) ───────────────────────


def run_payload(
    mine_id: str,
    panel_id: str,
    expected_mine_version: int,
    planned_tons: float = 6000,
    hoist_window_start: str = "2026-08-02T00:00:00Z",
    hoist_window_end: str = "2026-08-02T06:00:00Z",
) -> Dict[str, Any]:
    return {
        "mine_id": mine_id,
        "panel_id": panel_id,
        "planned_tons": planned_tons,
        "hoist_window_start": hoist_window_start,
        "hoist_window_end": hoist_window_end,
        "expected_mine_version": expected_mine_version,
    }


def hoist_payload(hoisted_tons: float) -> Dict[str, Any]:
    return {"hoisted_tons": hoisted_tons}


# ─── Treatment batches (PRD §3.5) ─────────────────────


def batch_payload(
    production_run_id: str,
    depot_id: str,
    product_line: str = HIGHWAY_DEICING,
    screen_spec: str = COARSE,
    anticaking_ppm: float = 20.0,
    corrosion_inhibitor_pct: float = 0.5,
    input_tons: float = 6000,
    moisture_pct: float = 2.0,
    storage_kind: str = COVERED,
) -> Dict[str, Any]:
    return {
        "production_run_id": production_run_id,
        "depot_id": depot_id,
        "product_line": product_line,
        "screen_spec": screen_spec,
        "anticaking_ppm": anticaking_ppm,
        "corrosion_inhibitor_pct": corrosion_inhibitor_pct,
        "input_tons": input_tons,
        "moisture_pct": moisture_pct,
        "storage_kind": storage_kind,
    }


def qc_decision_payload(decision: str, note: Any = _UNSET) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    _put(payload, "note", note)
    return payload


# ─── Depots (PRD §3.6) ────────────────────────────────


def depot_payload(
    name: str = "Albany Market Depot",
    state_code: str = "NY",
    covered_capacity_tons: float = 40000,
    open_pad_capacity_tons: float = 20000,
    loadout_rate_tons_per_hour: float = 500,
    outbound_freight_rate_per_ton: float = 4.000,
) -> Dict[str, Any]:
    return {
        "name": name,
        "state_code": state_code,
        "covered_capacity_tons": covered_capacity_tons,
        "open_pad_capacity_tons": open_pad_capacity_tons,
        "loadout_rate_tons_per_hour": loadout_rate_tons_per_hour,
        "outbound_freight_rate_per_ton": outbound_freight_rate_per_ton,
    }


def depot_patch_payload(
    covered_capacity_tons: Any = _UNSET,
    open_pad_capacity_tons: Any = _UNSET,
    loadout_rate_tons_per_hour: Any = _UNSET,
    outbound_freight_rate_per_ton: Any = _UNSET,
) -> Dict[str, Any]:
    """Any subset of the four revisable fields (PRD §3.6)."""
    payload: Dict[str, Any] = {}
    _put(payload, "covered_capacity_tons", covered_capacity_tons)
    _put(payload, "open_pad_capacity_tons", open_pad_capacity_tons)
    _put(payload, "loadout_rate_tons_per_hour", loadout_rate_tons_per_hour)
    _put(payload, "outbound_freight_rate_per_ton", outbound_freight_rate_per_ton)
    return payload


def posture_payload(depot_state: str, reason: Any = _UNSET) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"depot_state": depot_state}
    _put(payload, "reason", reason)
    return payload


def quarantine_payload(
    quarantine: bool, quarantine_reason: Any = _UNSET
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quarantine": quarantine}
    _put(payload, "quarantine_reason", quarantine_reason)
    return payload


# ─── Shipments (PRD §3.7) ─────────────────────────────


def shipment_payload(
    stockpile_lot_id: str,
    origin_depot_id: str,
    destination_depot_id: str,
    tons: float,
    load_window_start: str = "2026-08-05T08:00:00Z",
    load_window_end: str = "2026-08-05T10:00:00Z",
    mode: str = MODE_RAIL,
    destination_storage_kind: str = COVERED,
) -> Dict[str, Any]:
    return {
        "stockpile_lot_id": stockpile_lot_id,
        "origin_depot_id": origin_depot_id,
        "destination_depot_id": destination_depot_id,
        "mode": mode,
        "tons": tons,
        "load_window_start": load_window_start,
        "load_window_end": load_window_end,
        "destination_storage_kind": destination_storage_kind,
    }


def cancel_payload(reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return None if reason is None else {"reason": reason}


# ─── Season forecasts (PRD §3.8) ──────────────────────


def forecast_payload(
    season_code: str = "2026-27",
    region_code: str = "UPSTATE_NY",
    normal_season_tons: float = 200000,
    severity_index: int = 60,
    prior_season_1_actual_tons: float = 240000,
    prior_season_2_actual_tons: float = 180000,
    prior_season_3_actual_tons: float = 150000,
    method: str = METHOD_SEVERITY_WEIGHTED,
    preseason_lock_date: str = "2026-11-01T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "season_code": season_code,
        "region_code": region_code,
        "normal_season_tons": normal_season_tons,
        "severity_index": severity_index,
        "prior_season_1_actual_tons": prior_season_1_actual_tons,
        "prior_season_2_actual_tons": prior_season_2_actual_tons,
        "prior_season_3_actual_tons": prior_season_3_actual_tons,
        "method": method,
        "preseason_lock_date": preseason_lock_date,
    }


def forecast_patch_payload(
    severity_index: Any = _UNSET,
    method: Any = _UNSET,
    preseason_lock_date: Any = _UNSET,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    _put(payload, "severity_index", severity_index)
    _put(payload, "method", method)
    _put(payload, "preseason_lock_date", preseason_lock_date)
    return payload


# ─── Bid contracts (PRD §3.8) ─────────────────────────


def contract_payload(
    season_forecast_id: str,
    customer_name: str = "City of Syracuse",
    jurisdiction_level: str = JURISDICTION_MUNICIPAL,
    state_code: str = "NY",
    product_line: str = HIGHWAY_DEICING,
    committed_tons: float = 5000,
    guaranteed_price_per_ton: float = 68.55,
    min_take_pct: float = 80,
    max_take_pct: float = 110,
    failure_to_supply_penalty_per_ton: float = 22.00,
    price_guarantee_cap_pct: float = 10,
) -> Dict[str, Any]:
    return {
        "season_forecast_id": season_forecast_id,
        "customer_name": customer_name,
        "jurisdiction_level": jurisdiction_level,
        "state_code": state_code,
        "product_line": product_line,
        "committed_tons": committed_tons,
        "guaranteed_price_per_ton": guaranteed_price_per_ton,
        "min_take_pct": min_take_pct,
        "max_take_pct": max_take_pct,
        "failure_to_supply_penalty_per_ton": failure_to_supply_penalty_per_ton,
        "price_guarantee_cap_pct": price_guarantee_cap_pct,
    }


def decision_payload(outcome: str, note: Any = _UNSET) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    _put(payload, "note", note)
    return payload


def note_payload(note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return None if note is None else {"note": note}


# ─── Delivery orders and allocations (PRD §3.9) ───────


def order_payload(
    bid_contract_id: str,
    depot_id: str,
    expected_bid_contract_version: int,
    requested_tons: float = 1000,
    required_by: str = "2026-12-15T00:00:00Z",
    market_index_price_per_ton: float = 70.00,
    storm_priority: Any = _UNSET,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "bid_contract_id": bid_contract_id,
        "depot_id": depot_id,
        "requested_tons": requested_tons,
        "required_by": required_by,
        "market_index_price_per_ton": market_index_price_per_ton,
        "expected_bid_contract_version": expected_bid_contract_version,
    }
    _put(payload, "storm_priority", storm_priority)
    return payload


def waiver_payload(
    waiver_reason: str = "Regional storm exhausted regional stockpile",
) -> Dict[str, Any]:
    return {"waiver_reason": waiver_reason}


def allocation_payload(
    delivery_order_id: str,
    stockpile_lot_id: str,
    tons: float,
    expected_stockpile_lot_version: int,
) -> Dict[str, Any]:
    return {
        "delivery_order_id": delivery_order_id,
        "stockpile_lot_id": stockpile_lot_id,
        "tons": tons,
        "expected_stockpile_lot_version": expected_stockpile_lot_version,
    }


def release_payload(reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return None if reason is None else {"reason": reason}
