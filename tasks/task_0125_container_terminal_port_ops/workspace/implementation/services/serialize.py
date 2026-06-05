"""Public serializers for each entity.

Strips internal bookkeeping (_seq) and exposes exactly the fields declared in
SCAFFOLD §1.1, including computed fields for Container.
"""
from __future__ import annotations

from typing import Any, Dict

import db
from services import demurrage


def _base_versioned(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _base_audit(r: Dict[str, Any]) -> Dict[str, Any]:
    # append-only audit records carry only id + created_at
    return {
        "id": r["id"],
        "created_at": r["created_at"],
    }


def berth(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    out.update({
        "code": r["code"],
        "length_m": r["length_m"],
        "draft_m": r["draft_m"],
        "status": r["status"],
    })
    return out


def vessel(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    out.update({
        "imo_number": r["imo_number"],
        "name": r["name"],
        "loa_m": r["loa_m"],
        "draft_m": r["draft_m"],
        "free_time_days": r["free_time_days"],
    })
    return out


def berth_window(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    out.update({
        "berth_id": r["berth_id"],
        "vessel_id": r["vessel_id"],
        "eta": r["eta"],
        "etd": r["etd"],
        "actual_berth_at": r["actual_berth_at"],
        "actual_depart_at": r["actual_depart_at"],
        "status": r["status"],
    })
    return out


def container(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    # free_time_expires_at and demurrage_due_cents are computed fields, derived
    # on read so a fetch reflects the discharge window's berth state and clock.
    expires = demurrage.free_time_expires_at(r)
    due = demurrage.compute(r)[1]
    r["free_time_expires_at"] = expires
    r["demurrage_due_cents"] = due
    out.update({
        "container_number": r["container_number"],
        "vessel_id": r["vessel_id"],
        "berth_window_id": r["berth_window_id"],
        "is_reefer": r["is_reefer"],
        "setpoint_c": r["setpoint_c"],
        "yard_slot_id": r["yard_slot_id"],
        "customs_status": r["customs_status"],
        "handling_status": r["handling_status"],
        "free_time_expires_at": expires,
        "demurrage_due_cents": due,
    })
    return out


def yard_slot(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    out.update({
        "block": r["block"],
        "bay": r["bay"],
        "row": r["row"],
        "tier": r["tier"],
        "is_reefer_rack": r["is_reefer_rack"],
        "below_slot_id": r["below_slot_id"],
        "occupied_by_container_id": r["occupied_by_container_id"],
        "status": r["status"],
    })
    return out


def gate_appointment(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    out.update({
        "container_id": r["container_id"],
        "truck_plate": r["truck_plate"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
        "no_show_count": r["no_show_count"],
    })
    return out


def customs_hold(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    out.update({
        "container_id": r["container_id"],
        "reason": r["reason"],
        "placed_at": r["placed_at"],
        "released_at": r["released_at"],
        "status": r["status"],
    })
    return out


def reefer_reading(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_audit(r)
    out.update({
        "container_id": r["container_id"],
        "recorded_at": r["recorded_at"],
        "temperature_c": r["temperature_c"],
        "is_excursion": r["is_excursion"],
    })
    return out


def eir(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_audit(r)
    out.update({
        "container_id": r["container_id"],
        "gate_appointment_id": r["gate_appointment_id"],
        "direction": r["direction"],
        "condition": r["condition"],
        "damage_note": r["damage_note"],
        "recorded_at": r["recorded_at"],
    })
    return out


def demurrage_invoice(r: Dict[str, Any]) -> Dict[str, Any]:
    out = _base_versioned(r)
    out.update({
        "container_id": r["container_id"],
        "chargeable_days": r["chargeable_days"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def clock() -> Dict[str, Any]:
    return db.clock_view()
