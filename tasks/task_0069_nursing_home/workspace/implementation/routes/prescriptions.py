"""Prescription + medication administration endpoints."""
from flask import request

from clock import iso_now, parse_date, parse_dt
from db import LOCK, get_db
from errors import APIError
from helpers import (new_entity, paginate, parse_pagination, require_body,
                     require_enum, require_field, touch)
from middleware import require_roles
from response import list_success, success
from services import audit, prescription as rx_svc


ADMIN_OUTCOME = {"ADMINISTERED", "REFUSED", "OMITTED", "ERROR"}


def _serialize(p):
    return dict(p)


def _serialize_admin(a):
    return dict(a)


def register(app):

    # POST /elders/{id}/prescriptions
    @app.post("/elders/<eid>/prescriptions")
    @require_roles("Physician")
    def create_prescription(user_id, role, eid):
        body = require_body()
        drug_code = require_field(body, "drug_code", str)
        drug_name = require_field(body, "drug_name", str)
        is_controlled = require_field(body, "is_controlled_substance", bool)
        contraind = body.get("contraindicated_allergens") or []
        interacts = body.get("interacts_with_drug_codes") or []
        if not isinstance(contraind, list) or not isinstance(interacts, list):
            raise APIError("ERR_VALIDATION", "Array fields have wrong type", 422)
        dose_mg = body.get("dose_mg")
        if dose_mg is None or isinstance(dose_mg, bool) or not isinstance(dose_mg, (int, float)):
            raise APIError("ERR_VALIDATION", "dose_mg must be a number", 422)
        if dose_mg <= 0:
            raise APIError("ERR_VALIDATION", "dose_mg must be > 0", 422)
        frequency = require_field(body, "frequency_per_day", int)
        if frequency < 1:
            raise APIError("ERR_VALIDATION", "frequency_per_day must be >= 1", 422)
        starts_on = require_field(body, "starts_on", str)
        ends_on = require_field(body, "ends_on", str)
        try:
            sd = parse_date(starts_on)
            ed = parse_date(ends_on)
        except Exception:
            raise APIError("ERR_VALIDATION", "starts_on/ends_on must be YYYY-MM-DD", 422)
        if ed < sd:
            raise APIError("ERR_VALIDATION", "ends_on must be >= starts_on", 422)
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            if elder.get("status") != "ADMITTED":
                raise APIError("ERR_INVALID_STATE",
                               "Elder must be ADMITTED to receive a prescription", 409)
            p = new_entity({
                "elder_id": eid,
                "drug_code": drug_code,
                "drug_name": drug_name,
                "is_controlled_substance": is_controlled,
                "contraindicated_allergens": contraind,
                "interacts_with_drug_codes": interacts,
                "dose_mg": dose_mg,
                "frequency_per_day": frequency,
                "prescriber_id": user_id,
                "status": "PENDING_REVIEW",
                "starts_on": starts_on,
                "ends_on": ends_on,
                "dispensing_schedule": [],
            })
            db.prescriptions[p["id"]] = p
            audit.log(role, user_id, "Prescription", p["id"],
                      "CREATE", None, "PENDING_REVIEW")
            return success(_serialize(p), status=201)

    @app.post("/prescriptions/<pid>/activate")
    @require_roles("Supervisor")
    def activate_rx(user_id, role, pid):
        with LOCK:
            db = get_db()
            p = db.prescriptions.get(pid)
            if p is None:
                raise APIError("ERR_NOT_FOUND", f"Prescription {pid} not found", 404)
            rx_svc.activate(p, user_id, role)
            return success(_serialize(p))

    @app.post("/prescriptions/<pid>/suspend")
    @require_roles("Physician")
    def suspend_rx(user_id, role, pid):
        with LOCK:
            db = get_db()
            p = db.prescriptions.get(pid)
            if p is None:
                raise APIError("ERR_NOT_FOUND", f"Prescription {pid} not found", 404)
            rx_svc.suspend(p, user_id, role)
            return success(_serialize(p))

    @app.post("/prescriptions/<pid>/resume")
    @require_roles("Physician")
    def resume_rx(user_id, role, pid):
        with LOCK:
            db = get_db()
            p = db.prescriptions.get(pid)
            if p is None:
                raise APIError("ERR_NOT_FOUND", f"Prescription {pid} not found", 404)
            rx_svc.resume(p, user_id, role)
            return success(_serialize(p))

    @app.post("/prescriptions/<pid>/discontinue")
    @require_roles("Physician")
    def discontinue_rx(user_id, role, pid):
        with LOCK:
            db = get_db()
            p = db.prescriptions.get(pid)
            if p is None:
                raise APIError("ERR_NOT_FOUND", f"Prescription {pid} not found", 404)
            rx_svc.discontinue(p, user_id, role)
            return success(_serialize(p))

    @app.post("/prescriptions/<pid>/administrations")
    @require_roles("Nurse")
    def administer_rx(user_id, role, pid):
        body = require_body()
        scheduled_slot_at = require_field(body, "scheduled_slot_at", str)
        outcome = require_enum(body, "outcome", ADMIN_OUTCOME)
        witness_id = body.get("witness_id")
        with LOCK:
            db = get_db()
            p = db.prescriptions.get(pid)
            if p is None:
                raise APIError("ERR_NOT_FOUND", f"Prescription {pid} not found", 404)
            # State precondition: only ACTIVE prescriptions can be administered
            if p["status"] != "ACTIVE":
                raise APIError("ERR_INVALID_STATE",
                               f"Prescription is {p['status']}, not ACTIVE", 409)
            # Priority 7: segregation of duties — nurse cannot be prescriber
            if user_id == p["prescriber_id"]:
                raise APIError("ERR_SEGREGATION_OF_DUTIES",
                               "Recording nurse must differ from prescriber", 403)
            # Priority 8: controlled-substance witness required, distinct
            if p["is_controlled_substance"]:
                if not witness_id or witness_id == user_id or witness_id == p["prescriber_id"]:
                    raise APIError("ERR_WITNESS_REQUIRED",
                                   "Controlled substance requires distinct witness_id", 422)
            # Priority 19: slot must be in generated schedule
            schedule = db.prescription_schedules.get(pid) or p.get("dispensing_schedule") or []
            if scheduled_slot_at not in schedule:
                raise APIError("ERR_SLOT_NOT_SCHEDULED",
                               "scheduled_slot_at not in dispensing schedule", 422)
            # Slot uniqueness — concurrency: ERR_SLOT_ALREADY_ADMINISTERED
            for a in db.administrations.values():
                if a["prescription_id"] == pid and a["scheduled_slot_at"] == scheduled_slot_at:
                    raise APIError("ERR_SLOT_ALREADY_ADMINISTERED",
                                   "An administration already exists for this slot", 409)
            adm = new_entity({
                "prescription_id": pid,
                "scheduled_slot_at": scheduled_slot_at,
                "administered_at": iso_now(),
                "nurse_id": user_id,
                "witness_id": witness_id,
                "outcome": outcome,
                "error_report_id": None,
            }, versioned=False)
            db.administrations[adm["id"]] = adm

            # If outcome==ERROR, auto-create a MedicationErrorReport stub
            if outcome == "ERROR":
                err_type = body.get("error_type") or "OTHER"
                severity = body.get("severity") or "MINOR"
                description = body.get("description") or ""
                if err_type not in {"WRONG_DRUG", "WRONG_DOSE", "WRONG_TIME", "INTERACTION", "OTHER"}:
                    raise APIError("ERR_VALIDATION", "Invalid error_type", 422)
                if severity not in {"MINOR", "MODERATE", "SEVERE"}:
                    raise APIError("ERR_VALIDATION", "Invalid severity", 422)
                err = new_entity({
                    "administration_id": adm["id"],
                    "prescription_id": pid,
                    "elder_id": p["elder_id"],
                    "error_type": err_type,
                    "severity": severity,
                    "description": description,
                }, versioned=False)
                db.medication_errors[err["id"]] = err
                adm["error_report_id"] = err["id"]
                audit.log(role, user_id, "MedicationAdministration", adm["id"],
                          "ERROR_REPORT", None, outcome)

            audit.log(role, user_id, "MedicationAdministration", adm["id"],
                      "ADMINISTER", None, outcome)
            return success(_serialize_admin(adm), status=201)

    @app.get("/prescriptions/<pid>")
    @require_roles("Admin", "Supervisor", "Physician", "Nurse")
    def get_rx(user_id, role, pid):
        db = get_db()
        p = db.prescriptions.get(pid)
        if p is None:
            raise APIError("ERR_NOT_FOUND", f"Prescription {pid} not found", 404)
        out = _serialize(p)
        out["dispensing_schedule"] = db.prescription_schedules.get(pid) or p.get("dispensing_schedule") or []
        return success(out)

    @app.get("/prescriptions/<pid>/administrations")
    @require_roles("Admin", "Supervisor", "Physician", "Nurse")
    def list_admins(user_id, role, pid):
        limit, offset = parse_pagination()
        outcome_f = request.args.get("outcome")
        db = get_db()
        if db.prescriptions.get(pid) is None:
            raise APIError("ERR_NOT_FOUND", f"Prescription {pid} not found", 404)
        items = [a for a in db.administrations.values() if a["prescription_id"] == pid]
        if outcome_f:
            items = [a for a in items if a["outcome"] == outcome_f]
        items.sort(key=lambda a: a["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize_admin(a) for a in page], limit, offset, total)
