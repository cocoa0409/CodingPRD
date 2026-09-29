"""Request-payload builders.

Each factory returns only the client-supplied fields for its endpoint — never a
server-generated field such as ``id``, a computed counter, or a lifecycle state.
Every factory accepts ``**overrides`` so a test can vary exactly the one input
its scenario turns on.
"""

import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def unique_code(prefix: str = "CODE") -> str:
    """A code that is unique within a single test run."""
    return f"{prefix}-{next(_counter):05d}"


# ─── The logical clock ──────────────────────────────────────────────────────


def clock_payload(to_iso8601: str, **overrides) -> Dict[str, Any]:
    """Body for repositioning the logical clock."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ─── NetworkLoop ───────────────────────────────────────────────────────────


def network_loop_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": unique_code("LOOP"),
        "name": "Central District Loop",
        "service_mode": "HEATING",
        "design_supply_temp_c": 95.0,
        "max_pressure_kpa": 1600.0,
        "rated_capacity_kw": 10000.0,
    }
    payload.update(overrides)
    return payload


# ─── PipeSegment ───────────────────────────────────────────────────────────


def pipe_segment_payload(loop_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loop_id": loop_id,
        "code": unique_code("SEG"),
        "length_m": 800.0,
        "diameter_mm": 250.0,
        "install_year": 2010,
        "insulation_class": "A",
        "buried_depth_m": 1.4,
    }
    payload.update(overrides)
    return payload


def condition_assessment_payload(
    makeup_water_ratio: float,
    historical_leak_count: int,
    insulation_class: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "makeup_water_ratio": makeup_water_ratio,
        "historical_leak_count": historical_leak_count,
        "insulation_class": insulation_class,
    }
    payload.update(overrides)
    return payload


# ─── FuelSupplyContract ────────────────────────────────────────────────────


def fuel_supply_contract_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supplier_code": unique_code("FC"),
        "fuel_type": "NATURAL_GAS",
        "contracted_energy_mwh_per_year": 50000.0,
        "price_per_mwh": 42.00,
        "delivery_firmness": "FIRM",
    }
    payload.update(overrides)
    return payload


def fuel_contract_status_payload(status: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return payload


# ─── ProductionAsset ───────────────────────────────────────────────────────


def production_asset_payload(loop_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loop_id": loop_id,
        "code": unique_code("AST"),
        "asset_type": "BOILER",
        "rated_capacity_kw": 2000.0,
        "marginal_cost_per_mwh": 45.00,
        "emission_factor_kg_per_mwh": 200.0,
    }
    payload.update(overrides)
    return payload


def availability_payload(availability_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"availability_state": availability_state}
    payload.update(overrides)
    return payload


# ─── LoadForecast ──────────────────────────────────────────────────────────


def load_forecast_payload(loop_id: str, service_date: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loop_id": loop_id,
        "service_date": service_date,
        "occupancy_profile": "WEEKDAY_FULL",
    }
    payload.update(overrides)
    return payload


def publish_forecast_payload(variant: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"variant": variant}
    payload.update(overrides)
    return payload


# ─── DispatchPlan ──────────────────────────────────────────────────────────


def dispatch_plan_payload(
    loop_id: str, forecast_id: str, expected_loop_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loop_id": loop_id,
        "forecast_id": forecast_id,
        "expected_loop_version": expected_loop_version,
    }
    payload.update(overrides)
    return payload


def plan_review_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── RateSchedule ──────────────────────────────────────────────────────────


def rate_schedule_payload(
    customer_class: str = "COMMERCIAL_OFFICE",
    tiers: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": unique_code("RS"),
        "customer_class": customer_class,
        "fixed_service_charge": 800.00,
        "demand_charge_per_kw": 12.00,
        "minimum_bill_amount": 4000.00,
        "tiers": tiers
        if tiers is not None
        else [
            {"load_factor_max": 30.0, "energy_rate_per_mwh": 88.00},
            {"load_factor_max": 65.0, "energy_rate_per_mwh": 74.00},
            {"load_factor_max": 100.0, "energy_rate_per_mwh": 61.00},
        ],
    }
    payload.update(overrides)
    return payload


# ─── ConnectionAgreement ───────────────────────────────────────────────────


def connection_agreement_payload(
    loop_id: str, rate_schedule_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loop_id": loop_id,
        "rate_schedule_id": rate_schedule_id,
        "customer_name": "Riverside Tower",
        "customer_class": "COMMERCIAL_OFFICE",
        "reserved_capacity_kw": 1000.0,
        "service_mode": "HEATING",
        "service_start_date": "2026-01-01T00:00:00Z",
        "service_end_date": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def agreement_status_payload(contract_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"contract_state": contract_state}
    payload.update(overrides)
    return payload


# ─── MeteringPoint ─────────────────────────────────────────────────────────


def metering_point_payload(agreement_id: str, segment_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agreement_id": agreement_id,
        "segment_id": segment_id,
        "code": unique_code("MP"),
    }
    payload.update(overrides)
    return payload


def meter_reading_payload(
    read_at: str,
    cumulative_energy_mwh: float,
    peak_demand_kw: float,
    read_type: str = "ACTUAL",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "read_at": read_at,
        "cumulative_energy_mwh": cumulative_energy_mwh,
        "peak_demand_kw": peak_demand_kw,
        "read_type": read_type,
    }
    payload.update(overrides)
    return payload


# ─── Invoice ───────────────────────────────────────────────────────────────


def invoice_payload(
    agreement_id: str,
    period_start: str,
    period_end: str,
    variant: str,
    expected_agreement_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agreement_id": agreement_id,
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def invoice_adjust_payload(variant: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"variant": variant}
    payload.update(overrides)
    return payload


def payment_payload(amount: float, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount": amount}
    payload.update(overrides)
    return payload


# ─── WorkOrder ─────────────────────────────────────────────────────────────


def work_order_payload(
    segment_id: str, loop_id: str, window_start: str, window_end: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "segment_id": segment_id,
        "loop_id": loop_id,
        "work_type": "INSPECTION",
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def permit_decision_payload(permit_decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"permit_decision": permit_decision}
    payload.update(overrides)
    return payload


# ─── ExpansionProject ──────────────────────────────────────────────────────


def expansion_project_payload(
    loop_id: str, rate_schedule_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loop_id": loop_id,
        "rate_schedule_id": rate_schedule_id,
        "candidate_customer_name": "Northgate Campus",
        "customer_class": "COMMERCIAL_OFFICE",
        "requested_capacity_kw": 1200.0,
        "route_length_m": 850.0,
        "assumed_annual_energy_mwh": 4200.0,
        "assumed_marginal_cost_per_mwh": 38.00,
        "design_delta_t_c": 40.0,
    }
    payload.update(overrides)
    return payload


def sizing_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def project_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def convert_project_payload(
    reserved_capacity_kw: float,
    service_mode: str,
    service_start_date: str,
    service_end_date: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reserved_capacity_kw": reserved_capacity_kw,
        "service_mode": service_mode,
        "service_start_date": service_start_date,
        "service_end_date": service_end_date,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_code",
    "clock_payload",
    "network_loop_payload",
    "pipe_segment_payload",
    "condition_assessment_payload",
    "fuel_supply_contract_payload",
    "fuel_contract_status_payload",
    "production_asset_payload",
    "availability_payload",
    "load_forecast_payload",
    "publish_forecast_payload",
    "dispatch_plan_payload",
    "plan_review_payload",
    "rate_schedule_payload",
    "connection_agreement_payload",
    "agreement_status_payload",
    "metering_point_payload",
    "meter_reading_payload",
    "invoice_payload",
    "invoice_adjust_payload",
    "payment_payload",
    "work_order_payload",
    "permit_decision_payload",
    "expansion_project_payload",
    "sizing_payload",
    "project_decision_payload",
    "convert_project_payload",
]
