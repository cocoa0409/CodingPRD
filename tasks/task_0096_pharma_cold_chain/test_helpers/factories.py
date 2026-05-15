"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body. Tests pass overrides for the values they want to control.
Only PRD-declared input fields are produced; computed and system fields
are intentionally omitted.

Per PRD §2.4, identifiers are bare UUIDs (no prefix). Time-bearing
fields are integer minutes in the per-warehouse deterministic clock
coordinate (PRD §2.7).
"""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Random suffix for uniqueness (warehouse codes, zone codes, bin codes,
# supplier/product names, SKUs, lot numbers).
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


# ---------------------------------------------------------------------------
# Warehouse (PRD §3.1)
# Required input: code, name, gsp_license_no.
# ---------------------------------------------------------------------------
def create_warehouse_payload(
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    gsp_license_no: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "code": code or f"W{suffix}",
        "name": name or f"Warehouse {suffix}",
        "gsp_license_no": gsp_license_no or f"GSP-{suffix}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Zone (PRD §3.1)
# Required: code, zone_type, target_temp_low_c, target_temp_high_c,
#           alarm_low_c, alarm_high_c, capacity_units.
# ---------------------------------------------------------------------------
def create_zone_payload(
    *,
    code: Optional[str] = None,
    zone_type: str = "REFRIGERATED",
    target_temp_low_c: Optional[float] = None,
    target_temp_high_c: Optional[float] = None,
    alarm_low_c: Optional[float] = None,
    alarm_high_c: Optional[float] = None,
    capacity_units: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    # Default temperature bands depending on zone_type.
    defaults_map = {
        "REFRIGERATED": (
            TEST_DEFAULTS["REFRIGERATED_TARGET_LOW_C"],
            TEST_DEFAULTS["REFRIGERATED_TARGET_HIGH_C"],
            TEST_DEFAULTS["REFRIGERATED_ALARM_LOW_C"],
            TEST_DEFAULTS["REFRIGERATED_ALARM_HIGH_C"],
        ),
        "FROZEN": (
            TEST_DEFAULTS["FROZEN_TARGET_LOW_C"],
            TEST_DEFAULTS["FROZEN_TARGET_HIGH_C"],
            TEST_DEFAULTS["FROZEN_ALARM_LOW_C"],
            TEST_DEFAULTS["FROZEN_ALARM_HIGH_C"],
        ),
        "COOL": (
            TEST_DEFAULTS["COOL_TARGET_LOW_C"],
            TEST_DEFAULTS["COOL_TARGET_HIGH_C"],
            TEST_DEFAULTS["COOL_ALARM_LOW_C"],
            TEST_DEFAULTS["COOL_ALARM_HIGH_C"],
        ),
        "ROOM_TEMP": (
            TEST_DEFAULTS["ROOM_TEMP_TARGET_LOW_C"],
            TEST_DEFAULTS["ROOM_TEMP_TARGET_HIGH_C"],
            TEST_DEFAULTS["ROOM_TEMP_ALARM_LOW_C"],
            TEST_DEFAULTS["ROOM_TEMP_ALARM_HIGH_C"],
        ),
        # CONTROLLED_TEMP — wider band.
        "CONTROLLED_TEMP": (15.0, 25.0, 10.0, 30.0),
        # QUARANTINE — wide band (zone is non-conforming storage).
        "QUARANTINE": (2.0, 25.0, 0.0, 30.0),
    }
    dlow, dhigh, alow, ahigh = defaults_map.get(
        zone_type,
        (TEST_DEFAULTS["REFRIGERATED_TARGET_LOW_C"],
         TEST_DEFAULTS["REFRIGERATED_TARGET_HIGH_C"],
         TEST_DEFAULTS["REFRIGERATED_ALARM_LOW_C"],
         TEST_DEFAULTS["REFRIGERATED_ALARM_HIGH_C"]),
    )
    payload: Dict[str, Any] = {
        "code": code or f"Z{suffix}",
        "zone_type": zone_type,
        "target_temp_low_c": (
            target_temp_low_c if target_temp_low_c is not None else dlow
        ),
        "target_temp_high_c": (
            target_temp_high_c if target_temp_high_c is not None else dhigh
        ),
        "alarm_low_c": (
            alarm_low_c if alarm_low_c is not None else alow
        ),
        "alarm_high_c": (
            alarm_high_c if alarm_high_c is not None else ahigh
        ),
        "capacity_units": (
            capacity_units if capacity_units is not None
            else TEST_DEFAULTS["ZONE_CAPACITY_UNITS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bin (PRD §3.1)
# Required: code, volume_units, weight_limit_kg. Optional: special_storage_tag.
# ---------------------------------------------------------------------------
def create_bin_payload(
    *,
    code: Optional[str] = None,
    volume_units: Optional[int] = None,
    weight_limit_kg: Optional[float] = None,
    special_storage_tag: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "code": code or f"B{suffix}",
        "volume_units": (
            volume_units if volume_units is not None
            else TEST_DEFAULTS["BIN_VOLUME_UNITS"]
        ),
        "weight_limit_kg": (
            weight_limit_kg if weight_limit_kg is not None
            else TEST_DEFAULTS["BIN_WEIGHT_LIMIT_KG"]
        ),
    }
    if special_storage_tag is not None:
        payload["special_storage_tag"] = special_storage_tag
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Supplier (PRD §3.1)
# Required: name, qualification_expiry_minutes. Optional: qualified
# (default true per PRD).
# ---------------------------------------------------------------------------
def create_supplier_payload(
    *,
    name: Optional[str] = None,
    qualified: Optional[bool] = None,
    qualification_expiry_minutes: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "name": name or f"Supplier {suffix}",
        "qualification_expiry_minutes": (
            qualification_expiry_minutes
            if qualification_expiry_minutes is not None
            else TEST_DEFAULTS["QUALIFICATION_EXPIRY_MINUTES"]
        ),
    }
    if qualified is not None:
        payload["qualified"] = qualified
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Product (PRD §3.1)
# Required: sku, name, required_zone_type, unit_weight_kg,
# stability_budget_minutes. Optional: special_storage_tag, qualified.
# ---------------------------------------------------------------------------
def create_product_payload(
    *,
    sku: Optional[str] = None,
    name: Optional[str] = None,
    required_zone_type: str = "REFRIGERATED",
    special_storage_tag: Optional[str] = None,
    qualified: Optional[bool] = None,
    unit_weight_kg: Optional[float] = None,
    stability_budget_minutes: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "sku": sku or f"SKU-{suffix}",
        "name": name or f"Product {suffix}",
        "required_zone_type": required_zone_type,
        "unit_weight_kg": (
            unit_weight_kg if unit_weight_kg is not None
            else TEST_DEFAULTS["UNIT_WEIGHT_KG"]
        ),
        "stability_budget_minutes": (
            stability_budget_minutes
            if stability_budget_minutes is not None
            else TEST_DEFAULTS["STABILITY_BUDGET_MINUTES"]
        ),
    }
    if special_storage_tag is not None:
        payload["special_storage_tag"] = special_storage_tag
    if qualified is not None:
        payload["qualified"] = qualified
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InboundReceipt (PRD §3.2)
# Required: supplier_id, product_id, lot_number, expiry_minutes,
# quantity_units, carrier_logger_readings, visual_pass.
# ---------------------------------------------------------------------------
def create_receipt_payload(
    *,
    supplier_id: str,
    product_id: str,
    lot_number: Optional[str] = None,
    expiry_minutes: Optional[int] = None,
    quantity_units: Optional[int] = None,
    carrier_logger_readings: Optional[List[Dict[str, Any]]] = None,
    visual_pass: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "supplier_id": supplier_id,
        "product_id": product_id,
        "lot_number": lot_number or f"LOT-{suffix}",
        "expiry_minutes": (
            expiry_minutes if expiry_minutes is not None
            else TEST_DEFAULTS["LOT_EXPIRY_MINUTES"]
        ),
        "quantity_units": (
            quantity_units if quantity_units is not None
            else TEST_DEFAULTS["RECEIPT_QUANTITY_UNITS"]
        ),
        # Two-entry monotonic logger trace, both inside a REFRIGERATED
        # 2..8 C band by default; override per test as needed.
        "carrier_logger_readings": (
            carrier_logger_readings if carrier_logger_readings is not None
            else [
                {"minutes": 0, "temp_c": 5.0},
                {"minutes": 1, "temp_c": 5.0},
            ]
        ),
        "visual_pass": visual_pass,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OutboundShipment (PRD §3.5)
# Required: customer_id, product_id, quantity_units, packaging_kind,
# pick_temp_c, vehicle_precondition_temp_c.
# ---------------------------------------------------------------------------
def create_shipment_payload(
    *,
    customer_id: Optional[str] = None,
    product_id: str,
    quantity_units: Optional[int] = None,
    packaging_kind: str = "INSULATED_PCM",
    pick_temp_c: float = 5.0,
    vehicle_precondition_temp_c: float = 5.0,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "customer_id": customer_id or f"customer-{suffix}",
        "product_id": product_id,
        "quantity_units": quantity_units if quantity_units is not None else 1,
        "packaging_kind": packaging_kind,
        "pick_temp_c": pick_temp_c,
        "vehicle_precondition_temp_c": vehicle_precondition_temp_c,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TemperatureEvent (PRD §3.3)
# Required: at_minutes, temp_c.
# ---------------------------------------------------------------------------
def temperature_event_payload(
    *,
    at_minutes: int,
    temp_c: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "at_minutes": at_minutes,
        "temp_c": temp_c,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deviation assess (PRD §3.3)
# Required: qa_decision. Optional: capa_id (required when classification
# is MAJOR/CRITICAL and qa_decision == RELEASE).
# ---------------------------------------------------------------------------
def assess_deviation_payload(
    *,
    qa_decision: str = "RELEASE",
    capa_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"qa_decision": qa_decision}
    if capa_id is not None:
        payload["capa_id"] = capa_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recall (PRD §3.7)
# Required (create): classification, reason.
# Required (scope): lot_id, units, scope_kind. Optional: shipment_id.
# Required (record-return): scope_entry_id, units.
# ---------------------------------------------------------------------------
def create_recall_payload(
    *,
    classification: str = "CLASS_II",
    reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "classification": classification,
        "reason": reason or "Test recall reason",
    }
    payload.update(overrides)
    return payload


def add_scope_payload(
    *,
    lot_id: str,
    units: int,
    scope_kind: str,
    shipment_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_id": lot_id,
        "units": units,
        "scope_kind": scope_kind,
    }
    if shipment_id is not None:
        payload["shipment_id"] = shipment_id
    payload.update(overrides)
    return payload


def record_return_payload(
    *,
    scope_entry_id: str,
    units: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scope_entry_id": scope_entry_id,
        "units": units,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.7)
# Required: minutes.
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    minutes: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"minutes": minutes}
    payload.update(overrides)
    return payload


__all__ = [
    "random_suffix",
    "create_warehouse_payload",
    "create_zone_payload",
    "create_bin_payload",
    "create_supplier_payload",
    "create_product_payload",
    "create_receipt_payload",
    "create_shipment_payload",
    "temperature_event_payload",
    "assess_deviation_payload",
    "create_recall_payload",
    "add_scope_payload",
    "record_return_payload",
    "clock_advance_payload",
]
