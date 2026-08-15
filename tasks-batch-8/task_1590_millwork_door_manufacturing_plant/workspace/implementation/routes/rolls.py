"""FireLabelRoll endpoints (PRD §3.1/§3.6)."""

from flask import Blueprint, request

import db
from errors import err
from middleware import get_context, require_role, json_body, req_string, req_enum, require_existence
from response import success, list_response, parse_pagination

bp = Blueprint("rolls", __name__)

LABEL_SERIES = ("UL_20MIN", "UL_45MIN", "UL_90MIN")


def serialize_roll(r):
    return {
        "id": r["id"],
        "label_series": r["label_series"],
        "serial_capacity": r["serial_capacity"],
        "serials_issued": r["serials_issued"],
        "serials_applied": r["serials_applied"],
        "serials_spoiled": r["serials_spoiled"],
        "serials_available": r["serials_available"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.post("/fire-label-rolls")
def create_roll():
    _, role = get_context()
    require_role(role, "PlantManager")
    body = json_body(required=("label_series", "serial_capacity"))
    label_series = req_enum(body, "label_series", LABEL_SERIES)
    capacity = body.get("serial_capacity")
    if isinstance(capacity, bool) or not isinstance(capacity, int):
        raise err("ERR_INVALID_REQUEST", "serial_capacity must be an integer")
    rec = db.new_record()
    rec.update({
        "label_series": label_series,
        "serial_capacity": capacity,
        "serials_issued": 0,
        "serials_applied": 0,
        "serials_spoiled": 0,
        "serials_available": capacity,
        "status": "ACTIVE",
    })
    db.fire_label_rolls[rec["id"]] = rec
    return success(serialize_roll(rec), status=201)


@bp.get("/fire-label-rolls")
def list_rolls():
    get_context()
    limit, offset = parse_pagination(request.args)
    series = request.args.get("label_series")
    status = request.args.get("status")
    items = [r for r in db.fire_label_rolls.values()
             if (series is None or r["label_series"] == series)
             and (status is None or r["status"] == status)]
    return list_response(items, limit, offset, serialize_roll)


@bp.get("/fire-label-rolls/<rid>")
def get_roll(rid):
    get_context()
    roll = require_existence(db.fire_label_rolls, rid, "ERR_ROLL_NOT_FOUND", "FireLabelRoll")
    return success(serialize_roll(roll))


@bp.put("/fire-label-rolls/<rid>/status")
def transition_roll(rid):
    _, role = get_context()
    require_role(role, "LabelAuthority")
    roll = require_existence(db.fire_label_rolls, rid, "ERR_ROLL_NOT_FOUND", "FireLabelRoll")
    body = json_body(required=("target_status",))
    target = req_string(body, "target_status")
    if target not in ("ACTIVE", "DEPLETED", "RETIRED"):
        raise err("ERR_INVALID_ROLL_STATUS_TRANSITION", "Unknown roll status: %s" % target)
    if not (roll["status"] == "ACTIVE" and target == "RETIRED"):
        raise err("ERR_INVALID_ROLL_STATUS_TRANSITION",
                  "Roll cannot transition from %s to %s" % (roll["status"], target))
    if roll["serials_issued"] != 0:
        raise err("ERR_OUTSTANDING_SERIALS", "Roll retire requires serials_issued == 0")
    roll["status"] = "RETIRED"
    db.touch(roll)
    return success(serialize_roll(roll))
