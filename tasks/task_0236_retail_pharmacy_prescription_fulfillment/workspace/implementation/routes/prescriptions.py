"""Prescription intake and lifecycle (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    get_body, require_field, opt_field, as_string, as_int,
    stamp_create, touch, get_pagination, paginate,
)
from clock import parse_iso, format_iso
from errors import err
from middleware import get_actor, require_roles
from response import object_response, array_response
from services import domain

bp = Blueprint("prescriptions", __name__)

ALL_ROLES = ["PharmacyAdmin", "Pharmacist", "Technician", "Cashier"]
CONTROLLED = {"CII", "CIII", "CIV", "CV"}
# Non-terminal workflow states other than ENTERED that block discontinue.
OPEN_BLOCKING_STATES = {"DUR_REVIEW", "ADJUDICATING", "PA_REFERRAL", "READY_FILL", "WILL_CALL"}


def serialize_prescription(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "patient_id": p["patient_id"],
        "prescriber_id": p["prescriber_id"], "drug_id": p["drug_id"],
        "quantity_per_fill": p["quantity_per_fill"], "days_supply": p["days_supply"],
        "refills_authorized": p["refills_authorized"],
        "refills_remaining": p["refills_remaining"], "written_utc": p["written_utc"],
        "expires_utc": p["expires_utc"], "last_dispensed_utc": p["last_dispensed_utc"],
        "status": p["status"],
    }


@bp.route("/prescriptions", methods=["POST"])
def create_prescription():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin", "Technician"])
    body = get_body()
    patient_id = as_string(require_field(body, "patient_id"), "patient_id")
    prescriber_id = as_string(require_field(body, "prescriber_id"), "prescriber_id")
    drug_id = as_string(require_field(body, "drug_id"), "drug_id")
    qty = as_int(require_field(body, "quantity_per_fill"), "quantity_per_fill", minimum=1)
    days = as_int(require_field(body, "days_supply"), "days_supply", minimum=1)
    refills_auth = as_int(opt_field(body, "refills_authorized", 0), "refills_authorized", minimum=0)
    written_raw = require_field(body, "written_utc")
    try:
        written_dt = parse_iso(as_string(written_raw, "written_utc"))
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "written_utc must be an ISO 8601 timestamp")
    with db.LOCK:
        # FK existence (priority 4).
        patient = db.patients.get(patient_id)
        if patient is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "patient_id does not reference a patient")
        prescriber = db.prescribers.get(prescriber_id)
        if prescriber is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "prescriber_id does not reference a prescriber")
        drug = db.drug_products.get(drug_id)
        if drug is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "drug_id does not reference a drug")
        is_controlled = drug["dea_schedule"] in CONTROLLED
        # Priority 7: prescriber DEA standing for controlled drugs.
        if is_controlled:
            if not prescriber.get("dea_number") or not prescriber.get("dea_active"):
                raise err("ERR_PRESCRIBER_DEA_INVALID",
                          "Controlled prescription requires an active DEA registration")
        # Priority 8: drug must be ACTIVE.
        if drug["status"] != "ACTIVE":
            raise err("ERR_DRUG_DISCONTINUED", "Drug product is discontinued")
        # expires_utc: +365d non-controlled, +180d controlled.
        days_to_expiry = 180 if is_controlled else 365
        expires_dt = written_dt + timedelta(days=days_to_expiry)
        rx = {
            "patient_id": patient_id, "prescriber_id": prescriber_id, "drug_id": drug_id,
            "quantity_per_fill": qty, "days_supply": days,
            "refills_authorized": refills_auth, "refills_remaining": refills_auth,
            "written_utc": format_iso(written_dt),
            "expires_utc": format_iso(expires_dt),
            "last_dispensed_utc": None, "status": "ACTIVE",
        }
        stamp_create(rx)
        db.prescriptions[rx["id"]] = rx
    return object_response(serialize_prescription(rx), 201)


@bp.route("/prescriptions", methods=["GET"])
def list_prescriptions():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    patient_id = request.args.get("patient_id")
    prescriber_id = request.args.get("prescriber_id")
    drug_id = request.args.get("drug_id")
    items = list(db.prescriptions.values())
    if patient_id is not None:
        items = [p for p in items if p["patient_id"] == patient_id]
    if prescriber_id is not None:
        items = [p for p in items if p["prescriber_id"] == prescriber_id]
    if drug_id is not None:
        items = [p for p in items if p["drug_id"] == drug_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_prescription(p) for p in page], limit, offset, total)


@bp.route("/prescriptions/<rid>", methods=["GET"])
def get_prescription(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    rx = db.prescriptions.get(rid)
    if rx is None:
        raise err("ERR_NOT_FOUND", "Prescription not found")
    return object_response(serialize_prescription(rx), 200)


@bp.route("/prescriptions/<rid>/discontinue", methods=["POST"])
def discontinue_prescription(rid):
    _uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    with db.LOCK:
        rx = db.prescriptions.get(rid)
        if rx is None:
            raise err("ERR_NOT_FOUND", "Prescription not found")
        if rx["status"] != "ACTIVE":
            raise err("ERR_PRESCRIPTION_NOT_ACTIVE", "Prescription is not ACTIVE")
        # No fill in a non-terminal workflow state other than ENTERED.
        for f in db.fills.values():
            if f["prescription_id"] != rx["id"]:
                continue
            if f["status"] in OPEN_BLOCKING_STATES:
                raise err("ERR_OPEN_FILL_EXISTS",
                          "An open fill prevents discontinuation")
        rx["status"] = "DISCONTINUED"
        touch(rx)
        # Cascade: each ENTERED fill -> CANCELLED.
        for f in db.fills.values():
            if f["prescription_id"] == rx["id"] and f["status"] == "ENTERED":
                f["status"] = "CANCELLED"
                touch(f)
        domain.recompute_refills_remaining(rx)
    return object_response(serialize_prescription(rx), 200)


@bp.route("/prescriptions/<rid>/expire-scan", methods=["POST"])
def expire_scan(rid):
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    with db.LOCK:
        rx = db.prescriptions.get(rid)
        if rx is None:
            raise err("ERR_NOT_FOUND", "Prescription not found")
        cur = parse_iso(db.current_utc())
        expires = parse_iso(rx["expires_utc"])
        if rx["status"] == "ACTIVE" and cur > expires:
            rx["status"] = "EXPIRED"
            touch(rx)
    return object_response(serialize_prescription(rx), 200)
