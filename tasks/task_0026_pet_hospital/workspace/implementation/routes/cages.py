"""Cages and Hospitalizations (PRD §3.8)."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, g, request

import db
from clock import now_iso, now_utc
from errors import err
from middleware import authenticate, require_roles
from response import success_object
from services.common import bump, init_full
from validators import (
    require_int,
    require_str,
    _CAGE_CODE_RE,
)

bp = Blueprint("cages", __name__)


ADMISSION_HOLD_CENTS = 50_000
HOSPITAL_DAY_UNIT_PRICE_CENTS = 4_000  # 40.00 per hospital-day


@bp.before_request
def _auth():
    authenticate()


# Cages -----------------------------------------------------------------
@bp.post("/cages")
def create_cage():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    code = payload.get("cage_code")
    if not isinstance(code, str) or not _CAGE_CODE_RE.match(code):
        raise err("ERR_VALIDATION_FAILED", "cage_code invalid")
    ward = payload.get("ward_code")
    if ward not in {"ISOLATION", "GENERAL", "ICU"}:
        raise err("ERR_VALIDATION_FAILED", "ward_code invalid")
    capacity = payload.get("capacity")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1 or capacity > 4:
        raise err("ERR_VALIDATION_FAILED", "capacity must be in [1,4]")
    with db.GLOBAL_LOCK:
        if db.cage_by_code(code):
            raise err("ERR_VALIDATION_FAILED", "cage_code must be unique")
        c = {
            "cage_code": code,
            "ward_code": ward,
            "capacity": int(capacity),
            "occupancy_count": 0,
        }
        init_full(c)
        db.cages[c["id"]] = c
        return success_object(cage_view(c), status=201)


# Hospitalizations ------------------------------------------------------
@bp.post("/hospitalizations")
def create_hospitalization():
    require_roles("DraftingVet")
    payload = request.get_json(silent=True) or {}
    visit_id = payload.get("visit_id")
    cage_id = payload.get("cage_id")
    if not isinstance(visit_id, str) or not isinstance(cage_id, str):
        raise err("ERR_VALIDATION_FAILED", "visit_id and cage_id required")
    with db.GLOBAL_LOCK:
        v = db.visits.get(visit_id)
        if not v:
            raise err("ERR_REFERENCE_NOT_FOUND", "visit_id not found")
        cage = db.cages.get(cage_id)
        if not cage:
            raise err("ERR_REFERENCE_NOT_FOUND", "cage_id not found")
        if v.get("status") != "CONSULT_DONE":
            raise err("ERR_INVALID_STATE", "Visit must be CONSULT_DONE to admit")
        # Cage capacity check (atomic).
        if int(cage.get("occupancy_count", 0)) >= int(cage.get("capacity", 0)):
            raise err("ERR_CAGE_CAPACITY_EXCEEDED", "Cage at capacity")
        # Owner deposit floor.
        pet = db.pets.get(v.get("pet_id")) or {}
        owner = db.owners.get(pet.get("owner_id")) or {}
        if int(owner.get("deposit_balance_cents", 0)) < ADMISSION_HOLD_CENTS:
            raise err("ERR_INSUFFICIENT_DEPOSIT", "Deposit below admission hold")
        # All checks pass; admit.
        h = {
            "visit_id": visit_id,
            "cage_id": cage_id,
            "admitted_at": now_iso(),
            "discharged_at": None,
            "daily_care_log": [],
            "status": "ADMITTED",
        }
        init_full(h)
        db.hospitalizations[h["id"]] = h
        # Side effects.
        cage["occupancy_count"] = int(cage["occupancy_count"]) + 1
        bump(cage)
        owner["deposit_balance_cents"] = int(owner["deposit_balance_cents"]) - ADMISSION_HOLD_CENTS
        bump(owner)
        v["status"] = "HOSPITALIZED"
        bump(v)
        return success_object(hosp_view(h), status=201)


@bp.post("/hospitalizations/<h_id>/begin-care")
def begin_care(h_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        h = db.hospitalizations.get(h_id)
        if not h:
            raise err("ERR_NOT_FOUND", f"Hospitalization {h_id} not found")
        if h["status"] != "ADMITTED":
            raise err("ERR_INVALID_STATE", "begin-care requires ADMITTED")
        h["status"] = "IN_CARE"
        bump(h)
        return success_object(hosp_view(h))


@bp.post("/hospitalizations/<h_id>/care-log")
def append_care_log(h_id):
    require_roles("DraftingVet")
    payload = request.get_json(silent=True) or {}
    note = payload.get("note")
    treatment_executed = payload.get("treatment_executed")
    if not isinstance(note, str):
        raise err("ERR_VALIDATION_FAILED", "note required")
    if not isinstance(treatment_executed, bool):
        raise err("ERR_VALIDATION_FAILED", "treatment_executed must be bool")
    with db.GLOBAL_LOCK:
        h = db.hospitalizations.get(h_id)
        if not h:
            raise err("ERR_NOT_FOUND", f"Hospitalization {h_id} not found")
        if h["status"] not in {"ADMITTED", "IN_CARE"}:
            raise err("ERR_INVALID_STATE", "care-log allowed only in ADMITTED/IN_CARE")
        h.setdefault("daily_care_log", []).append({
            "logged_at": now_iso(),
            "note": note,
            "treatment_executed": bool(treatment_executed),
        })
        bump(h)
        return success_object(hosp_view(h))


@bp.post("/hospitalizations/<h_id>/request-discharge")
def request_discharge(h_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        h = db.hospitalizations.get(h_id)
        if not h:
            raise err("ERR_NOT_FOUND", f"Hospitalization {h_id} not found")
        if h["status"] != "IN_CARE":
            raise err("ERR_INVALID_STATE", "request-discharge requires IN_CARE")
        # Prescription gate.
        for rx in db.prescriptions_for_visit(h["visit_id"]):
            if rx.get("status") not in {"DISPENSED", "REJECTED", "CANCELLED"}:
                raise err(
                    "ERR_PENDING_PRESCRIPTIONS",
                    "Open prescriptions remain on visit",
                )
        h["status"] = "DISCHARGE_PENDING"
        bump(h)
        return success_object(hosp_view(h))


@bp.post("/hospitalizations/<h_id>/discharge")
def discharge(h_id):
    require_roles("Cashier")
    with db.GLOBAL_LOCK:
        h = db.hospitalizations.get(h_id)
        if not h:
            raise err("ERR_NOT_FOUND", f"Hospitalization {h_id} not found")
        if h["status"] != "DISCHARGE_PENDING":
            raise err("ERR_INVALID_STATE", "discharge requires DISCHARGE_PENDING")
        bill = db.bill_for_visit(h["visit_id"])
        if not bill or bill.get("status") not in {"ISSUED", "PARTIALLY_PAID", "PAID", "INVOICED"}:
            raise err("ERR_INVALID_STATE", "Bill must be ISSUED/PARTIALLY_PAID/PAID/INVOICED")
        h["discharged_at"] = now_iso()
        h["status"] = "DISCHARGED"
        bump(h)
        # Decrement cage occupancy.
        cage = db.cages.get(h["cage_id"])
        if cage:
            cage["occupancy_count"] = max(0, int(cage["occupancy_count"]) - 1)
            bump(cage)
        # Append HOSPITAL_DAY line items per calendar day spanned.
        days = _days_spanned(h["admitted_at"], h["discharged_at"])
        if days < 1:
            days = 1
        from services.bill_calc import per_line_total_cents, recompute_provisional
        for _ in range(days):
            line = {
                "kind": "HOSPITAL_DAY",
                "ref_id": h["id"],
                "qty": 1,
                "unit_price_cents": HOSPITAL_DAY_UNIT_PRICE_CENTS,
                "line_total_cents": per_line_total_cents(1, HOSPITAL_DAY_UNIT_PRICE_CENTS),
            }
            bill.setdefault("line_items", []).append(line)
        recompute_provisional(bill)
        bump(bill)
        return success_object(hosp_view(h))


@bp.post("/hospitalizations/<h_id>/cancel")
def cancel_hospitalization(h_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        h = db.hospitalizations.get(h_id)
        if not h:
            raise err("ERR_NOT_FOUND", f"Hospitalization {h_id} not found")
        if h["status"] != "ADMITTED":
            raise err("ERR_INVALID_STATE", "cancel allowed only from ADMITTED")
        for entry in h.get("daily_care_log", []):
            if entry.get("treatment_executed") is True:
                raise err("ERR_INVALID_STATE", "Cannot cancel after treatment_executed")
        h["status"] = "CANCELLED"
        bump(h)
        cage = db.cages.get(h["cage_id"])
        if cage:
            cage["occupancy_count"] = max(0, int(cage["occupancy_count"]) - 1)
            bump(cage)
        v = db.visits.get(h["visit_id"])
        pet = db.pets.get(v.get("pet_id")) if v else None
        owner = db.owners.get(pet.get("owner_id")) if pet else None
        if owner:
            owner["deposit_balance_cents"] = int(owner["deposit_balance_cents"]) + ADMISSION_HOLD_CENTS
            bump(owner)
        # Return visit to CONSULT_DONE if it was HOSPITALIZED with no other open hosps.
        if v and v.get("status") == "HOSPITALIZED":
            other_active = any(
                hh.get("status") in {"ADMITTED", "IN_CARE", "DISCHARGE_PENDING"}
                for hh in db.hospitalizations_for_visit(v["id"])
                if hh["id"] != h["id"]
            )
            if not other_active:
                v["status"] = "CONSULT_DONE"
                bump(v)
        return success_object(hosp_view(h))


def _days_spanned(start_iso: str, end_iso: str) -> int:
    """Number of calendar days spanned between two ISO timestamps (UTC)."""
    from datetime import datetime
    s = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    e = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    sd = s.date()
    ed = e.date()
    return max(1, (ed - sd).days + 1)


def cage_view(c):
    return {
        "id": c["id"],
        "cage_code": c["cage_code"],
        "ward_code": c["ward_code"],
        "capacity": c["capacity"],
        "occupancy_count": int(c.get("occupancy_count", 0)),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def hosp_view(h):
    return {
        "id": h["id"],
        "visit_id": h["visit_id"],
        "cage_id": h["cage_id"],
        "admitted_at": h["admitted_at"],
        "discharged_at": h.get("discharged_at"),
        "daily_care_log": list(h.get("daily_care_log", [])),
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }
