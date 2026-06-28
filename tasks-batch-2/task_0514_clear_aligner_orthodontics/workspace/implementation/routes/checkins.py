"""ProgressCheckin endpoints (PRD §3.9, §2.4 append-only exception).

A ProgressCheckin carries only id and created_at — no updated_at, no version.
"""
from flask import Blueprint

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize
from response import object_response
from services.store import get_case, get_checkin
from validation import get_body, require_int, require_number, require_enum

bp = Blueprint("checkins", __name__)


@bp.route("/cases/<cid>/checkins", methods=["POST"])
def create_checkin(cid):
    _, role = get_auth()
    require_roles(role, {"Patient"})
    case = get_case(cid)
    body = get_body()
    reported_step_index = require_int(body, "reported_step_index")
    if reported_step_index < 1:
        raise err("ERR_INVALID_REQUEST", "reported_step_index must be >= 1.")
    photo_quality_score = require_number(body, "photo_quality_score")
    if photo_quality_score < 0.0 or photo_quality_score > 1.0:
        raise err("ERR_INVALID_REQUEST",
                  "photo_quality_score must be between 0.0 and 1.0.")

    # append-only: no updated_at / version
    rec = base_record(common_fields=False)
    rec.update({
        "case_id": cid,
        "reported_step_index": reported_step_index,
        "photo_quality_score": photo_quality_score,
        "tracking_assessment": "PENDING",
    })
    db.checkins[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/checkins/<chid>/assess", methods=["POST"])
def assess_checkin(chid):
    _, role = get_auth()
    require_roles(role, {"Clinician"})
    rec = get_checkin(chid)
    body = get_body()
    assessment = require_enum(body, "tracking_assessment", {"ON_TRACK", "OFF_TRACK"})
    # recording an assessment on an immutable submission: no version bump
    rec["tracking_assessment"] = assessment
    return object_response(serialize(rec), status=200)


@bp.route("/checkins/<chid>", methods=["GET"])
def fetch_checkin(chid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    rec = get_checkin(chid)
    return object_response(serialize(rec), status=200)
