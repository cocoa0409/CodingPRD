"""RampSlot endpoints — cyclic PPR machine (PRD §3.9)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, parse_datetime, _parse_iso,
                     pagination_params, paginate)

bp = Blueprint("ramp_slots", __name__)


def slot_view(s):
    return {
        "id": s["id"],
        "service_visit_id": s["service_visit_id"],
        "pad_id": s["pad_id"],
        "window_start_utc": s["window_start_utc"],
        "window_end_utc": s["window_end_utc"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _owner_operator_id(slot):
    visit = db.service_visits.get(slot["service_visit_id"])
    return visit["operator_id"] if visit else None


def _half_open_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@bp.route("/ramp-slots", methods=["POST"])
def create_slot():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    body = get_json()
    service_visit_id = require_string(body, "service_visit_id")
    pad_id = require_string(body, "pad_id")
    start = parse_datetime(body, "window_start_utc")
    end = parse_datetime(body, "window_end_utc")

    visit = db.service_visits.get(service_visit_id)
    if visit is None:
        raise err(errors.ERR_NOT_FOUND, "Service visit not found.")
    pad = db.parking_spots.get(pad_id)
    if pad is None:
        raise err(errors.ERR_NOT_FOUND, "Pad (parking spot) not found.")
    if role == "Operator" and user_id != visit["operator_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may request only for its own visits.")
    if not (end > start):
        raise err(errors.ERR_INVALID_INTERVAL, "window_end_utc must be strictly after window_start_utc.")

    s = db.common_create()
    s.update({
        "service_visit_id": service_visit_id,
        "pad_id": pad_id,
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "status": "REQUESTED",
    })
    db.ramp_slots[s["id"]] = s
    return success(slot_view(s), 201)


@bp.route("/ramp-slots/<id>", methods=["GET"])
def get_slot(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    s = db.ramp_slots.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp slot not found.")
    if role == "Operator" and user_id != _owner_operator_id(s):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own slots.")
    return success(slot_view(s), 200)


@bp.route("/ramp-slots", methods=["GET"])
def list_slots():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    limit, offset = pagination_params()
    records = list(db.ramp_slots.values())
    if role == "Operator":
        records = [r for r in records if _owner_operator_id(r) == user_id]
    v_f = request.args.get("service_visit_id")
    p_f = request.args.get("pad_id")
    st_f = request.args.get("status")
    if v_f is not None:
        records = [r for r in records if r["service_visit_id"] == v_f]
    if p_f is not None:
        records = [r for r in records if r["pad_id"] == p_f]
    if st_f is not None:
        records = [r for r in records if r["status"] == st_f]
    window, total = paginate(records, limit, offset)
    return list_response([slot_view(r) for r in window], limit, offset, total)


@bp.route("/ramp-slots/<id>/approve", methods=["POST"])
def approve(id):
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    s = db.ramp_slots.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp slot not found.")
    if s["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "approve requires REQUESTED status.")
    visit = db.service_visits.get(s["service_visit_id"])
    if visit["status"] not in ("SCHEDULED", "ON_GROUND", "SERVICING"):
        raise err(errors.ERR_INVALID_STATE, "Parent visit not in an approvable state.")
    # No other APPROVED slot on the same pad half-open-overlaps this window.
    s_start = _parse_iso(s["window_start_utc"])
    s_end = _parse_iso(s["window_end_utc"])
    for other in db.ramp_slots.values():
        if other["id"] == s["id"]:
            continue
        if other["pad_id"] != s["pad_id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        o_start = _parse_iso(other["window_start_utc"])
        o_end = _parse_iso(other["window_end_utc"])
        if _half_open_overlap(s_start, s_end, o_start, o_end):
            raise err(errors.ERR_SLOT_OVERLAP, "Slot overlaps an approved slot on the pad.")
    s["status"] = "APPROVED"
    db.touch(s)
    return success(slot_view(s), 200)


@bp.route("/ramp-slots/<id>/revoke", methods=["POST"])
def revoke(id):
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    s = db.ramp_slots.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp slot not found.")
    if s["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "revoke requires APPROVED status.")
    s["status"] = "REVOKED"
    db.touch(s)
    return success(slot_view(s), 200)


@bp.route("/ramp-slots/<id>/re-request", methods=["POST"])
def re_request(id):
    user_id, role = authenticate()
    require_role(role, {"Operator", "OpsDispatcher"})
    s = db.ramp_slots.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp slot not found.")
    # Ownership check for Operator role (must own the visit).
    if role == "Operator" and user_id != _owner_operator_id(s):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may re-request only its own slots.")
    if s["status"] != "REVOKED":
        raise err(errors.ERR_INVALID_STATE, "re-request requires REVOKED status.")
    visit = db.service_visits.get(s["service_visit_id"])
    if visit["status"] in ("DEPARTED", "CANCELLED"):
        raise err(errors.ERR_INVALID_STATE, "Parent visit is terminal.")
    s["status"] = "REQUESTED"
    db.touch(s)
    return success(slot_view(s), 200)


@bp.route("/ramp-slots/<id>/use", methods=["POST"])
def use(id):
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    s = db.ramp_slots.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp slot not found.")
    if s["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "use requires APPROVED status.")
    visit = db.service_visits.get(s["service_visit_id"])
    if visit["status"] not in ("ON_GROUND", "SERVICING", "READY_FOR_DEPARTURE"):
        raise err(errors.ERR_INVALID_STATE, "Parent visit not in a usable state.")
    s["status"] = "USED"
    db.touch(s)
    return success(slot_view(s), 200)
