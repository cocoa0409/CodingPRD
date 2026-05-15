"""Payload factories — one per endpoint that takes a body.

Only fields listed as input in PRD §3 / §4. Each factory accepts
**overrides so individual tests can vary specific values without
re-typing the whole payload.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Station / ChargingSlot
# ---------------------------------------------------------------------------
def create_station_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 inputs: name, latitude, longitude, total_slots."""
    defaults: Dict[str, Any] = {
        "name": f"{TEST_DEFAULTS['STATION_NAME']}-{uuid.uuid4().hex[:8]}",
        "latitude": TEST_DEFAULTS["STATION_LAT"],
        "longitude": TEST_DEFAULTS["STATION_LON"],
        "total_slots": TEST_DEFAULTS["STATION_TOTAL_SLOTS"],
    }
    defaults.update(overrides)
    return defaults


def create_charging_slot_payload(slot_number: int,
                                 tou_zone: Optional[str] = None,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 inputs: slot_number, tou_zone (defaults to SHOULDER)."""
    payload: Dict[str, Any] = {"slot_number": slot_number}
    if tou_zone is not None:
        payload["tou_zone"] = tou_zone
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reference data — BatteryModel, VehicleModel, CompatibilityRule
# ---------------------------------------------------------------------------
def create_battery_model_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 inputs: code, rated_capacity_kwh, nominal_voltage,
    manufacturer, ev_soh_floor_pct?."""
    defaults: Dict[str, Any] = {
        "code": f"BM-{uuid.uuid4().hex[:8]}",
        "rated_capacity_kwh": TEST_DEFAULTS["BATTERY_MODEL_RATED_KWH"],
        "nominal_voltage": TEST_DEFAULTS["BATTERY_MODEL_NOMINAL_V"],
        "manufacturer": TEST_DEFAULTS["BATTERY_MODEL_MANUFACTURER"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_model_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 inputs: code, name, pack_voltage_min, pack_voltage_max."""
    defaults: Dict[str, Any] = {
        "code": f"VM-{uuid.uuid4().hex[:8]}",
        "name": TEST_DEFAULTS["VEHICLE_MODEL_NAME"],
        "pack_voltage_min": TEST_DEFAULTS["VEHICLE_MODEL_VMIN"],
        "pack_voltage_max": TEST_DEFAULTS["VEHICLE_MODEL_VMAX"],
    }
    defaults.update(overrides)
    return defaults


def create_compatibility_rule_payload(vehicle_model_code: str,
                                      battery_model_code: str,
                                      **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 inputs: vehicle_model_code, battery_model_code,
    connector_match?, bms_handshake_supported?."""
    defaults: Dict[str, Any] = {
        "vehicle_model_code": vehicle_model_code,
        "battery_model_code": battery_model_code,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------
def create_battery_payload(battery_model_code: str, station_id: str,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 inputs: serial_number, battery_model_code, station_id,
    warranty_expires_at, soc_pct?, soh_pct?."""
    defaults: Dict[str, Any] = {
        "serial_number": (
            f"{TEST_DEFAULTS['BATTERY_SERIAL_PREFIX']}-"
            f"{uuid.uuid4().hex[:12]}"
        ),
        "battery_model_code": battery_model_code,
        "station_id": station_id,
        "warranty_expires_at": TEST_DEFAULTS["WARRANTY_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def start_charging_payload(charging_slot_id: str,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input: charging_slot_id."""
    payload: Dict[str, Any] = {"charging_slot_id": charging_slot_id}
    payload.update(overrides)
    return payload


def finish_charging_payload(soc_pct: float = 100.0,
                            capacity_test_kwh: float = 50.0,
                            internal_resistance_mohm: float = 50.0,
                            avg_temperature_c: float = 25.0,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 inputs: soc_pct, capacity_test_kwh,
    internal_resistance_mohm, avg_temperature_c."""
    payload: Dict[str, Any] = {
        "soc_pct": soc_pct,
        "capacity_test_kwh": capacity_test_kwh,
        "internal_resistance_mohm": internal_resistance_mohm,
        "avg_temperature_c": avg_temperature_c,
    }
    payload.update(overrides)
    return payload


def report_fault_payload(reason: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input: reason?."""
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Member, Vehicle
# ---------------------------------------------------------------------------
def create_member_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 inputs: name, phone, subscription_tier?,
    subscription_swaps_remaining?."""
    defaults: Dict[str, Any] = {
        "name": TEST_DEFAULTS["MEMBER_NAME"],
        "phone": f"+1-555-{uuid.uuid4().hex[:7]}",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(vehicle_model_code: str, owner_member_id: str,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 inputs: vin, vehicle_model_code, owner_member_id,
    installed_battery_id?."""
    # vin must be 11..17 characters per PRD §3.1
    vin = f"VIN{uuid.uuid4().hex[:14].upper()}"  # 17 chars
    defaults: Dict[str, Any] = {
        "vin": vin,
        "vehicle_model_code": vehicle_model_code,
        "owner_member_id": owner_member_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Reservation
# ---------------------------------------------------------------------------
def create_reservation_payload(member_id: str, vehicle_id: str,
                               station_id: str, slot_start_at: str,
                               slot_end_at: str,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 inputs: member_id, vehicle_id, station_id, slot_start_at,
    slot_end_at."""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "station_id": station_id,
        "slot_start_at": slot_start_at,
        "slot_end_at": slot_end_at,
    }
    payload.update(overrides)
    return payload


def create_walk_in_payload(member_id: str, vehicle_id: str,
                           station_id: str,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 inputs: member_id, vehicle_id, station_id (walk-in: no
    client-supplied timestamps)."""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "station_id": station_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SwapEvent
# ---------------------------------------------------------------------------
def inspect_payload(outgoing_soc_pct: float,
                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4 input: outgoing_soc_pct."""
    payload: Dict[str, Any] = {"outgoing_soc_pct": outgoing_soc_pct}
    payload.update(overrides)
    return payload


def install_payload(verify: bool = True,
                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4 input: verify (the operator asserts BMS handshake passed)."""
    payload: Dict[str, Any] = {"verify": verify}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DispatchOrder
# ---------------------------------------------------------------------------
def create_dispatch_order_payload(source_station_id: str,
                                  dest_station_id: str,
                                  battery_id: str,
                                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6 inputs: source_station_id, dest_station_id, battery_id."""
    payload: Dict[str, Any] = {
        "source_station_id": source_station_id,
        "dest_station_id": dest_station_id,
        "battery_id": battery_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recalls
# ---------------------------------------------------------------------------
def create_recall_payload(battery_model_code: str,
                          serial_numbers: List[str],
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6 inputs: battery_model_code, serial_numbers."""
    payload: Dict[str, Any] = {
        "battery_model_code": battery_model_code,
        "serial_numbers": list(serial_numbers),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
def refund_payload(refund_cents: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7 input: refund_cents."""
    payload: Dict[str, Any] = {"refund_cents": refund_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-only clock advance
# ---------------------------------------------------------------------------
def clock_advance_payload(to_iso: str,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8 input: to_iso."""
    payload: Dict[str, Any] = {"to_iso": to_iso}
    payload.update(overrides)
    return payload


__all__ = [
    "create_station_payload",
    "create_charging_slot_payload",
    "create_battery_model_payload",
    "create_vehicle_model_payload",
    "create_compatibility_rule_payload",
    "create_battery_payload",
    "start_charging_payload",
    "finish_charging_payload",
    "report_fault_payload",
    "create_member_payload",
    "create_vehicle_payload",
    "create_reservation_payload",
    "create_walk_in_payload",
    "inspect_payload",
    "install_payload",
    "create_dispatch_order_payload",
    "create_recall_payload",
    "refund_payload",
    "clock_advance_payload",
]
