"""Payload factories — one per entity, input fields only.

Money and energy values are emitted as JSON numbers, never as strings.
"""

# The reference plant used throughout the suite: 100 MWh / 25 MW, a 27.5 MVA
# interconnection point, 12.0 MVAr of reactive capability and 80 MWh stored.
ASSET_DEFAULTS = {
    "name": "Mesa Verde BESS 1",
    "nameplate_energy_mwh": 100.0,
    "power_rating_mw": 25.0,
    "poi_mw_limit": 25.0,
    "poi_mva_limit": 27.5,
    "reactive_capability_mvar": 12.0,
    "initial_soc_mwh": 80.0,
    "degradation_cost_usd_per_mwh": 12.00,
    "warranty_throughput_limit_mwh": 40000.0,
    "commercial_operation_date": "2023-08-01T00:00:00Z",
    "cycle_limit_per_year": 365,
}


def create_storage_asset_payload(**overrides) -> dict:
    """Registration body carrying only the eleven required inputs."""
    payload = dict(ASSET_DEFAULTS)
    payload.update(overrides)
    return payload


def create_soc_reservation_payload(
    asset_id: str,
    expected_asset_version: int,
    purpose: str = "ENERGY_ARBITRAGE",
    reserved_mwh: float = 40.0,
    window_start: str = "2026-08-10T12:00:00Z",
    window_end: str = "2026-08-10T16:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "asset_id": asset_id,
        "purpose": purpose,
        "reserved_mwh": reserved_mwh,
        "window_start": window_start,
        "window_end": window_end,
        "expected_asset_version": expected_asset_version,
    }
    payload.update(overrides)
    return payload


def create_market_bid_payload(
    asset_id: str,
    reservation_id: str,
    market_type: str = "DAY_AHEAD",
    product: str = "ENERGY",
    direction: str = "DISCHARGE",
    delivery_start: str = "2026-08-10T12:00:00Z",
    delivery_end: str = "2026-08-10T16:00:00Z",
    offer_mw: float = 20.0,
    **overrides,
) -> dict:
    payload = {
        "asset_id": asset_id,
        "reservation_id": reservation_id,
        "market_type": market_type,
        "product": product,
        "direction": direction,
        "delivery_start": delivery_start,
        "delivery_end": delivery_end,
        "offer_mw": offer_mw,
    }
    payload.update(overrides)
    return payload


def clearing_result_payload(
    outcome: str = "CLEARED",
    cleared_price_usd_per_mwh: float = None,
    cleared_mw: float = None,
) -> dict:
    payload = {"outcome": outcome}
    if cleared_price_usd_per_mwh is not None:
        payload["cleared_price_usd_per_mwh"] = cleared_price_usd_per_mwh
    if cleared_mw is not None:
        payload["cleared_mw"] = cleared_mw
    return payload


def create_dispatch_instruction_payload(
    bid_id: str,
    asset_id: str,
    instructed_mw: float = 20.0,
    setpoint_start: str = "2026-08-10T12:00:00Z",
    setpoint_end: str = "2026-08-10T13:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "bid_id": bid_id,
        "asset_id": asset_id,
        "instructed_mw": instructed_mw,
        "setpoint_start": setpoint_start,
        "setpoint_end": setpoint_end,
    }
    payload.update(overrides)
    return payload


def create_telemetry_sample_payload(
    dispatch_id: str,
    sample_index: int,
    sampled_at: str,
    measured_mw: float = 20.0,
    measured_mvar: float = 0.0,
    soc_mwh_reading: float = 75.0,
    max_cell_temp_c: float = 32.0,
    **overrides,
) -> dict:
    payload = {
        "dispatch_id": dispatch_id,
        "sample_index": sample_index,
        "sampled_at": sampled_at,
        "measured_mw": measured_mw,
        "measured_mvar": measured_mvar,
        "soc_mwh_reading": soc_mwh_reading,
        "max_cell_temp_c": max_cell_temp_c,
    }
    payload.update(overrides)
    return payload


def create_safety_event_payload(
    asset_id: str,
    event_type: str = "THERMAL_ANOMALY",
    severity: str = "WARNING",
    detected_max_cell_temp_c: float = 66.0,
    **overrides,
) -> dict:
    payload = {
        "asset_id": asset_id,
        "event_type": event_type,
        "severity": severity,
        "detected_max_cell_temp_c": detected_max_cell_temp_c,
    }
    payload.update(overrides)
    return payload


def create_capacity_obligation_payload(
    asset_id: str,
    program_name: str = "ISO Capacity Auction 2026",
    program_year: int = 2026,
    committed_mw: float = 20.0,
    availability_hours_required: float = 8600.0,
    penalty_rate_usd_per_mw_hour: float = 45.00,
    **overrides,
) -> dict:
    payload = {
        "asset_id": asset_id,
        "program_name": program_name,
        "program_year": program_year,
        "committed_mw": committed_mw,
        "availability_hours_required": availability_hours_required,
        "penalty_rate_usd_per_mw_hour": penalty_rate_usd_per_mw_hour,
    }
    payload.update(overrides)
    return payload


def create_capacity_test_payload(
    asset_id: str,
    scheduled_date: str = "2026-08-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {"asset_id": asset_id, "scheduled_date": scheduled_date}
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(
    asset_id: str,
    capacity_test_id: str,
    claim_type: str = "CAPACITY_SHORTFALL",
    **overrides,
) -> dict:
    payload = {
        "asset_id": asset_id,
        "capacity_test_id": capacity_test_id,
        "claim_type": claim_type,
    }
    payload.update(overrides)
    return payload


def approve_claim_payload(
    remedy_install_date: str = "2026-09-01T00:00:00Z",
    remedy_outage_days: int = 3,
) -> dict:
    return {
        "decision": "APPROVE",
        "remedy_install_date": remedy_install_date,
        "remedy_outage_days": remedy_outage_days,
    }


def deny_claim_payload(denial_reason: str = "NO_SHORTFALL") -> dict:
    return {"decision": "DENY", "denial_reason": denial_reason}
