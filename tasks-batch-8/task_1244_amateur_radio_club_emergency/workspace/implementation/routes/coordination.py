"""Frequency coordination request endpoints (PRD §3.2): DRAFT -> SUBMITTED ->
GRANTED/RETURNED with a RETURNED -> DRAFT revision loop; supersede on create."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_FREQUENCY_OUT_OF_BAND, ERR_INVALID_STATE, ERR_STALE_VERSION, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import as_enum, as_num, as_str, body_json, need, opt, reject_unknown_fields, as_int

bp = Blueprint("coordination", __name__)

ADMIN = {"ClubAdmin"}
DECISION_OUTCOMES = {"GRANTED", "RETURNED"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


def _check_band(freq):
    """Frequency must lie inside [144.0, 148.0] or [420.0, 450.0] MHz."""
    if not ((144.0 <= freq <= 148.0) or (420.0 <= freq <= 450.0)):
        raise ApiError(ERR_FREQUENCY_OUT_OF_BAND, 422,
                       "requested_frequency_mhz outside recognized allocations")


@bp.post("/coordination-requests")
def create_coordination():
    _auth(ADMIN)
    body = body_json(request)
    reject_unknown_fields(body, {"repeater_id", "requested_frequency_mhz",
                                 "expected_repeater_version"})
    repeater_id = as_str(need(body, "repeater_id"), "repeater_id")
    repeater = svc.get_repeater(repeater_id)  # body FK existence
    freq = as_num(need(body, "requested_frequency_mhz"),
                  "requested_frequency_mhz")
    expected = as_int(need(body, "expected_repeater_version"),
                      "expected_repeater_version")
    # OCC (PRD §2.9): refuse to supersede on a stale view of the repeater.
    if expected != repeater["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_repeater_version does not match current version")
    _check_band(freq)
    # Supersede: existing DRAFT/SUBMITTED requests for this repeater withdraw.
    for c in svc.sorted_records("coordination_requests"):
        if (c["repeater_id"] == repeater["id"]
                and c["status"] in ("DRAFT", "SUBMITTED")):
            c["status"] = "WITHDRAWN"
            svc.touch(c)
    svc.touch(repeater)
    coord = {
        "repeater_id": repeater["id"],
        "requested_frequency_mhz": freq,
        "status": "DRAFT",
        "council_reference": None,
        "revision_number": 0,
        "submitted_at": None,
        "decision_at": None,
    }
    svc.stamp_new(coord)
    db.STORE["coordination_requests"][coord["id"]] = coord
    return success(svc.ser_coord(coord), "object", 201)


@bp.get("/coordination-requests")
def list_coordination():
    _auth(ADMIN)
    repeater_id = request.args.get("repeater_id")
    status = request.args.get("status")
    items = []
    for c in svc.sorted_records("coordination_requests"):
        if repeater_id is not None and c["repeater_id"] != repeater_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(svc.ser_coord(c))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/coordination-requests/<cid>")
def get_coordination(cid):
    _auth(ADMIN)
    return success(svc.ser_coord(svc.get_coord(cid)), "object", 200)


@bp.post("/coordination-requests/<cid>/submit")
def submit_coordination(cid):
    _auth(ADMIN)
    coord = svc.get_coord(cid)
    body = body_json(request)
    reject_unknown_fields(body, set())
    if coord["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT request can be submitted")
    coord["status"] = "SUBMITTED"
    coord["submitted_at"] = db.now()
    svc.touch(coord)
    return success(svc.ser_coord(coord), "object", 200)


@bp.post("/coordination-requests/<cid>/record-decision")
def record_decision(cid):
    _auth(ADMIN)
    coord = svc.get_coord(cid)
    body = body_json(request)
    reject_unknown_fields(body, {"outcome", "council_reference"})
    outcome = as_enum(need(body, "outcome"), "outcome", DECISION_OUTCOMES)
    council_reference = as_str(need(body, "council_reference"),
                               "council_reference")
    if coord["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "decisions are recorded only on SUBMITTED requests")
    coord["status"] = outcome
    coord["council_reference"] = council_reference
    coord["decision_at"] = db.now()
    svc.touch(coord)
    return success(svc.ser_coord(coord), "object", 200)


@bp.post("/coordination-requests/<cid>/revise")
def revise_coordination(cid):
    _auth(ADMIN)
    coord = svc.get_coord(cid)
    body = body_json(request)
    reject_unknown_fields(body, {"requested_frequency_mhz"})
    freq = opt(body, "requested_frequency_mhz")
    if freq is not None:
        freq = as_num(freq, "requested_frequency_mhz")
    if coord["status"] != "RETURNED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RETURNED request can be revised")
    if freq is not None:
        _check_band(freq)
        coord["requested_frequency_mhz"] = freq
    coord["status"] = "DRAFT"
    coord["revision_number"] += 1
    svc.touch(coord)
    return success(svc.ser_coord(coord), "object", 200)


@bp.post("/coordination-requests/<cid>/withdraw")
def withdraw_coordination(cid):
    _auth(ADMIN)
    coord = svc.get_coord(cid)
    body = body_json(request)
    reject_unknown_fields(body, set())
    if coord["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only DRAFT or SUBMITTED requests can be withdrawn")
    coord["status"] = "WITHDRAWN"
    svc.touch(coord)
    return success(svc.ser_coord(coord), "object", 200)
