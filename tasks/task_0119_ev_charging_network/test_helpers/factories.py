"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD §3 prose:
- Site: name, circuit_limit_kw, demand_charge_threshold_kw required;
  allocation_policy / demand_avoidance_armed optional.
- Stall: site_id, connector_type, max_power_kw required; reservation_priority optional.
- Tariff: pricing/tier/rate fields + window required; session_fee_cents,
  idle_grace_minutes, idle_fee_cents_per_min optional.
- Driver: email, full_name, home_emsp_id required.
- eMSP: name, commission_pct required.
- Reservation: stall_id, driver_id, window_start, window_end, expected_stall_version
  required; hold_fee_cents optional.
- Session: stall_id, driver_id required; reservation_id, is_roaming optional.
- MeterEvent: meter_kwh, sampled_at, reading_context required.
"""
from .constants import ENERGY_TARIFF


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Site",
        "circuit_limit_kw": 200,
        "demand_charge_threshold_kw": 200,
    }
    defaults.update(overrides)
    return defaults


def create_stall_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "connector_type": "CCS",
        "max_power_kw": 60,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(home_emsp_id: str, **overrides) -> dict:
    defaults = {
        "email": "driver@example.com",
        "full_name": "Test Driver",
        "home_emsp_id": home_emsp_id,
    }
    defaults.update(overrides)
    return defaults


def create_emsp_payload(**overrides) -> dict:
    defaults = {
        "name": "Test eMSP",
        "commission_pct": 0.075,
    }
    defaults.update(overrides)
    return defaults


def create_tariff_payload(site_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id, "connector_type": "CCS"}
    defaults.update(ENERGY_TARIFF)
    defaults.update(overrides)
    return defaults


def create_reservation_payload(
    stall_id: str, driver_id: str, expected_stall_version: int, **overrides
) -> dict:
    defaults = {
        "stall_id": stall_id,
        "driver_id": driver_id,
        "window_start": "2026-06-01T09:00:00Z",
        "window_end": "2026-06-01T10:00:00Z",
        "expected_stall_version": expected_stall_version,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(stall_id: str, driver_id: str, **overrides) -> dict:
    defaults = {"stall_id": stall_id, "driver_id": driver_id}
    defaults.update(overrides)
    return defaults


def create_meter_event_payload(meter_kwh, sampled_at, reading_context, **overrides) -> dict:
    defaults = {
        "meter_kwh": meter_kwh,
        "sampled_at": sampled_at,
        "reading_context": reading_context,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_batch_payload(emsp_id: str, **overrides) -> dict:
    defaults = {"emsp_id": emsp_id}
    defaults.update(overrides)
    return defaults


def create_line_item_payload(session_id: str, **overrides) -> dict:
    defaults = {"session_id": session_id}
    defaults.update(overrides)
    return defaults
