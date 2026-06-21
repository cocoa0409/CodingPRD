"""Existence lookups.

Path-id lookups raise ERR_NOT_FOUND (404, priority 3).
FK-body lookups raise ERR_FK_NOT_FOUND (404, priority 4).
"""
from __future__ import annotations

from typing import Any, Dict

import db
from errors import APIError, ERR_FK_NOT_FOUND, ERR_NOT_FOUND


def _get_or(store: Dict[str, Dict[str, Any]], rid: str, error_id: str, http: int, label: str):
    rec = store.get(rid)
    if rec is None:
        raise APIError(error_id, http, f"{label} not found: {rid}")
    return rec


# ---- path-id lookups (ERR_NOT_FOUND) ---------------------------------------
def path_berth(rid):     return _get_or(db.berths, rid, ERR_NOT_FOUND, 404, "berth")
def path_vessel(rid):    return _get_or(db.vessels, rid, ERR_NOT_FOUND, 404, "vessel")
def path_window(rid):    return _get_or(db.berth_windows, rid, ERR_NOT_FOUND, 404, "berth window")
def path_container(rid): return _get_or(db.containers, rid, ERR_NOT_FOUND, 404, "container")
def path_slot(rid):      return _get_or(db.yard_slots, rid, ERR_NOT_FOUND, 404, "yard slot")
def path_appt(rid):      return _get_or(db.gate_appointments, rid, ERR_NOT_FOUND, 404, "gate appointment")
def path_hold(rid):      return _get_or(db.customs_holds, rid, ERR_NOT_FOUND, 404, "customs hold")
def path_invoice(rid):   return _get_or(db.demurrage_invoices, rid, ERR_NOT_FOUND, 404, "demurrage invoice")


# ---- FK-body lookups (ERR_FK_NOT_FOUND) ------------------------------------
def fk_berth(rid):     return _get_or(db.berths, rid, ERR_FK_NOT_FOUND, 404, "berth_id")
def fk_vessel(rid):    return _get_or(db.vessels, rid, ERR_FK_NOT_FOUND, 404, "vessel_id")
def fk_window(rid):    return _get_or(db.berth_windows, rid, ERR_FK_NOT_FOUND, 404, "berth_window_id")
def fk_container(rid): return _get_or(db.containers, rid, ERR_FK_NOT_FOUND, 404, "container_id")
def fk_slot(rid):      return _get_or(db.yard_slots, rid, ERR_FK_NOT_FOUND, 404, "yard_slot_id")
def fk_appt(rid):      return _get_or(db.gate_appointments, rid, ERR_FK_NOT_FOUND, 404, "gate_appointment_id")
