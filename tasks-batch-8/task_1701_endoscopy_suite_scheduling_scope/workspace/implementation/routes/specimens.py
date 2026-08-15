"""Specimen chain-of-custody endpoints (PRD 3.8)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_SPECIMEN_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_BOOKING_NOT_IN_PROGRESS,
    ERR_PROVIDER_OWNERSHIP_MISMATCH,
    ERR_LABEL_WINDOW_EXCEEDED,
    ERR_TRANSPORT_WINDOW_EXCEEDED,
    ERR_SPECIMEN_NOT_LABELED,
    ERR_SPECIMEN_NOT_IN_TRANSIT,
    ERR_SPECIMEN_NOT_RECEIVED,
    ERR_SPECIMEN_TERMINAL,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from util import now
from validate import get_body, req_bool, req_enum, req_int, req_str, require_path_resource, resolve_ref

bp = Blueprint("specimens", __name__)

SPECIMEN_TYPES = {"POLYP", "BIOPSY", "OTHER"}
LABEL_WINDOW_MIN = 15
TRANSPORT_WINDOW_MIN = 120


@bp.post("/endoscopy/specimens")
def create_specimen():
    caller = authorized(["Endoscopist"])
    body = get_body()
    # Rung 3 (existence)
    booking = resolve_ref("bookings", body.get("booking_id"), ERR_BOOKING_NOT_FOUND)
    # Rung 4 (schema)
    req_str(body, "booking_id")
    specimen_type = req_enum(body, "specimen_type", SPECIMEN_TYPES)
    container_count = req_int(body, "container_count", minimum=1)
    # Rung 6 (ownership): collection belongs to the booking's own endoscopist.
    if caller.user_id != booking["provider_id"]:
        raise_error(ERR_PROVIDER_OWNERSHIP_MISMATCH,
                    "X-User-ID must equal the booking's provider_id")
    # Rung 7 (state): the booking must be IN_PROGRESS.
    if booking["status"] != "IN_PROGRESS":
        raise_error(ERR_BOOKING_NOT_IN_PROGRESS,
                    "specimen collection requires booking axis IN_PROGRESS")
    rec = new_record("specimens", {
        "booking_id": booking["id"],
        "patient_id": booking["patient_id"],
        "specimen_type": specimen_type,
        "container_count": container_count,
        "status": "COLLECTED",
        "collected_at": now(),
        "labeled_at": None,
        "labeled_by": None,
        "handed_off_at": None,
        "handed_off_by": None,
        "courier_id": None,
        "received_at": None,
        "received_by": None,
        "reject_reason": None,
        "adenoma_confirmed": None,
        "resulted_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/specimens")
def list_specimens():
    return list_response("specimens", {
        "booking_id": request.args.get("booking_id"),
        "patient_id": request.args.get("patient_id"),
        "status": request.args.get("status"),
    })


@bp.get("/endoscopy/specimens/<rid>")
def get_specimen(rid):
    return get_one("specimens", rid, ERR_SPECIMEN_NOT_FOUND)


@bp.post("/endoscopy/specimens/<rid>/label")
def label_specimen(rid):
    caller = authorized(["Endoscopist", "PathologyStaff"])
    specimen = require_path_resource("specimens", rid, ERR_SPECIMEN_NOT_FOUND)
    get_body()
    # Rung 7 (state): custody starts at COLLECTED.
    if specimen["status"] != "COLLECTED":
        raise_error(ERR_SPECIMEN_TERMINAL,
                    "label requires status COLLECTED")
    # Rung 8 (compliance): label within 15 minutes of collection, inclusive.
    if now() > specimen["collected_at"] + timedelta(minutes=LABEL_WINDOW_MIN):
        raise_error(ERR_LABEL_WINDOW_EXCEEDED,
                    "labeling later than collected_at + 15 minutes")
    specimen["status"] = "LABELED"
    specimen["labeled_at"] = now()
    specimen["labeled_by"] = caller.user_id
    touch(specimen)
    return success_object(public(specimen))


@bp.post("/endoscopy/specimens/<rid>/handoff")
def handoff_specimen(rid):
    caller = authorized(["PathologyStaff"])
    specimen = require_path_resource("specimens", rid, ERR_SPECIMEN_NOT_FOUND)
    body = get_body()
    courier_id = req_str(body, "courier_id")
    # Rung 7 (state)
    if specimen["status"] != "LABELED":
        raise_error(ERR_SPECIMEN_NOT_LABELED, "handoff requires status LABELED")
    specimen["status"] = "IN_TRANSIT"
    specimen["handed_off_at"] = now()
    specimen["handed_off_by"] = caller.user_id
    specimen["courier_id"] = courier_id
    touch(specimen)
    return success_object(public(specimen))


@bp.post("/endoscopy/specimens/<rid>/receive")
def receive_specimen(rid):
    caller = authorized(["PathologyStaff"])
    specimen = require_path_resource("specimens", rid, ERR_SPECIMEN_NOT_FOUND)
    get_body()
    # Rung 7 (state)
    if specimen["status"] != "IN_TRANSIT":
        raise_error(ERR_SPECIMEN_NOT_IN_TRANSIT, "receive requires status IN_TRANSIT")
    # Rung 8 (compliance): transport window collected_at + 120 min, inclusive.
    if now() > specimen["collected_at"] + timedelta(minutes=TRANSPORT_WINDOW_MIN):
        raise_error(ERR_TRANSPORT_WINDOW_EXCEEDED,
                    "receipt later than collected_at + 120 minutes")
    specimen["status"] = "RECEIVED_BY_LAB"
    specimen["received_at"] = now()
    specimen["received_by"] = caller.user_id
    touch(specimen)
    return success_object(public(specimen))


@bp.post("/endoscopy/specimens/<rid>/reject")
def reject_specimen(rid):
    authorized(["PathologyStaff"])
    specimen = require_path_resource("specimens", rid, ERR_SPECIMEN_NOT_FOUND)
    body = get_body()
    reason = req_str(body, "reason")
    # Rung 7 (state): rejection is available from LABELED or IN_TRANSIT only.
    if specimen["status"] not in ("LABELED", "IN_TRANSIT"):
        raise_error(ERR_SPECIMEN_TERMINAL,
                    "reject requires status LABELED or IN_TRANSIT")
    specimen["status"] = "REJECTED_BY_LAB"
    specimen["reject_reason"] = reason
    touch(specimen)
    return success_object(public(specimen))


@bp.post("/endoscopy/specimens/<rid>/result")
def result_specimen(rid):
    authorized(["PathologyStaff"])
    specimen = require_path_resource("specimens", rid, ERR_SPECIMEN_NOT_FOUND)
    body = get_body()
    adenoma_confirmed = req_bool(body, "adenoma_confirmed")
    # Rung 7 (state)
    if specimen["status"] != "RECEIVED_BY_LAB":
        raise_error(ERR_SPECIMEN_NOT_RECEIVED, "result requires status RECEIVED_BY_LAB")
    specimen["status"] = "RESULTED"
    specimen["adenoma_confirmed"] = adenoma_confirmed
    specimen["resulted_at"] = now()
    touch(specimen)
    return success_object(public(specimen))
