"""PSC appointments (PRD §3.7)."""
from flask import Blueprint, request

import db
import clock
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str,
    require_bool, paginate,
)
from services.orders import order_lines_for

bp = Blueprint("appointments", __name__)


def _order_requires_fasting(order_id):
    for ol in order_lines_for(order_id):
        offering = db.get("test_offerings", ol["test_offering_id"])
        if offering is not None and offering.get("requires_fasting"):
            return True
    return False


def _owns(role, user_id, patient_id):
    return not (role == "Patient" and user_id != patient_id)


@bp.route("/catalog/appointments", methods=["POST"])
def book_appointment():
    user_id, role = require_role(["Patient"])
    body = get_json()
    order_id = require_str(body, "order_id")
    psc_location_code = require_str(body, "psc_location_code")
    slot_start = require_str(body, "slot_start")
    slot_end = require_str(body, "slot_end")
    fasting_confirmed = require_bool(body, "fasting_confirmed", required=False, default=False)

    order = require_found("orders", order_id)
    if not _owns(role, user_id, order["patient_id"]):
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")

    try:
        start_dt = clock.parse_iso(slot_start)
        end_dt = clock.parse_iso(slot_end)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "slot_start/slot_end must be ISO 8601")

    # Slot window: slot_end strictly after slot_start.
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_SLOT_WINDOW", "slot_end must be after slot_start")

    # Overlap with existing BOOKED/CHECKED_IN at same location (half-open).
    for ap in db.all_rows("appointments"):
        if ap["psc_location_code"] != psc_location_code:
            continue
        if ap["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        ex_start = clock.parse_iso(ap["slot_start"])
        ex_end = clock.parse_iso(ap["slot_end"])
        # half-open [start, end): overlap unless they merely touch.
        if start_dt < ex_end and ex_start < end_dt:
            raise err("ERR_SLOT_OVERLAP", "Slot overlaps an existing appointment")

    # Fasting attestation.
    if _order_requires_fasting(order_id) and not fasting_confirmed:
        raise err("ERR_FASTING_NOT_CONFIRMED", "Fasting attestation required")

    rec = db.new_record({
        "order_id": order_id,
        "psc_location_code": psc_location_code,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "fasting_confirmed": fasting_confirmed,
        "status": "BOOKED",
    })
    db.insert("appointments", rec)
    return success(serialize(rec), status=201)


@bp.route("/catalog/appointments", methods=["GET"])
def list_appointments():
    user_id, role = require_role(["Patient", "CatalogAdmin", "PhlebotomyTech"])
    rows = db.sorted_rows(db.all_rows("appointments"))
    order_id = request.args.get("order_id")
    psc = request.args.get("psc_location_code")
    if order_id:
        rows = [r for r in rows if r["order_id"] == order_id]
    if psc:
        rows = [r for r in rows if r["psc_location_code"] == psc]
    if role == "Patient":
        owned = {o["id"] for o in db.all_rows("orders") if o["patient_id"] == user_id}
        rows = [r for r in rows if r["order_id"] in owned]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/appointments/<rid>", methods=["GET"])
def get_appointment(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin", "PhlebotomyTech"])
    rec = require_found("appointments", rid)
    if role == "Patient":
        order = db.get("orders", rec["order_id"])
        if order and user_id != order["patient_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(rec))


@bp.route("/catalog/appointments/<rid>/check-in", methods=["POST"])
def check_in(rid):
    require_role(["PhlebotomyTech"])
    rec = require_found("appointments", rid)
    # Check-in only from BOOKED.
    if rec["status"] != "BOOKED":
        raise err("ERR_APPOINTMENT_NOT_CHECKED_IN", "Appointment not in BOOKED state")
    # Re-validate fasting under the same rule.
    if _order_requires_fasting(rec["order_id"]) and not rec.get("fasting_confirmed"):
        raise err("ERR_FASTING_NOT_CONFIRMED", "Fasting attestation required")
    rec["status"] = "CHECKED_IN"
    db.touch(rec)
    return success(serialize(rec))
