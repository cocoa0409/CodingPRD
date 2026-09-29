"""Examination holds: placement, capacity, release (PRD 3.6)."""
from flask import Blueprint, request

from db import db, new_record, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import ok, ok_list, read_pagination, window
from services import calc, domain
import validate as v

bp = Blueprint("holds", __name__)

HOLD_TYPES = ("EXAM_NII", "EXAM_PHYSICAL", "DOCUMENT", "PGA", "SEAL_DISCREPANCY")
SCHEDULED_TYPES = ("EXAM_NII", "EXAM_PHYSICAL")
UNSCHEDULED_TYPES = ("DOCUMENT", "PGA")
FINDINGS_CODES = ("CLEAR", "DISCREPANCY", "SEAL_COMPROMISED")


@bp.route("/in-bond/examination-holds", methods=["POST"])
def place_hold():
    user_id, _role = require("CBPOfficer")
    body = v.get_body()
    movement_id = v.req_str(body, "movement_id")
    port_id = v.req_str(body, "port_id")
    hold_type = v.req_enum(body, "hold_type", HOLD_TYPES)
    reason_code = v.req_str(body, "reason_code")
    scheduled_start = v.opt_dt(body, "scheduled_start")
    scheduled_end = v.opt_dt(body, "scheduled_end")

    movement = db.movements.get(movement_id)
    if movement is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    port = db.ports.get(port_id)
    if port is None:
        raise ApiError("ERR_PORT_NOT_FOUND")

    # Band 9 - the movement must still be interruptible.
    if movement["transit_status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")
    if movement["custody_status"] in ("RELEASED", "GENERAL_ORDER"):
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")

    # Band 12 - the scheduled window.
    if hold_type in SCHEDULED_TYPES:
        if scheduled_start is None or scheduled_end is None:
            raise ApiError("ERR_EXAM_WINDOW_INVALID")
        if scheduled_end <= scheduled_start:
            raise ApiError("ERR_EXAM_WINDOW_INVALID")
    elif hold_type in UNSCHEDULED_TYPES:
        if scheduled_start is not None or scheduled_end is not None:
            raise ApiError("ERR_EXAM_WINDOW_INVALID")

    # Band 13 - bay capacity, then the system-only hold type.
    if hold_type in SCHEDULED_TYPES:
        occupancy = 0
        for other in domain.rows(db.holds):
            if other["port_id"] != port["id"] or other["status"] != "OPEN":
                continue
            if other["hold_type"] not in SCHEDULED_TYPES:
                continue
            if calc.windows_overlap(other["scheduled_start"], other["scheduled_end"],
                                    scheduled_start, scheduled_end):
                occupancy += 1
        if occupancy >= port["exam_capacity_slots"]:
            raise ApiError("ERR_EXAM_CAPACITY_EXCEEDED")
    if hold_type == "SEAL_DISCREPANCY":
        raise ApiError("ERR_HOLD_TYPE_NOT_ALLOWED")

    rec = new_record()
    rec.update({
        "movement_id": movement["id"],
        "port_id": port["id"],
        "hold_type": hold_type,
        "status": "OPEN",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "reason_code": reason_code,
        "placed_by_user_id": user_id,
        "released_at": None,
        "findings_code": None,
        "discrepancy_pieces": 0,
        "created_by_system": False,
    })
    db.holds[rec["id"]] = rec

    changed = False
    if movement["custody_status"] == "BONDED":
        movement["custody_status"] = "EXAM_HOLD"
        changed = True
    if domain.apply_go_grace(movement):
        changed = True
    if changed:
        touch(movement)
    domain.recompute_port(port)
    return ok(domain.hold_json(rec), 201)


@bp.route("/in-bond/examination-holds/<hold_id>", methods=["GET"])
def read_hold(hold_id):
    require(*ALL_ROLES)
    rec = db.holds.get(hold_id)
    if rec is None:
        raise ApiError("ERR_HOLD_NOT_FOUND")
    return ok(domain.hold_json(rec))


@bp.route("/in-bond/examination-holds", methods=["GET"])
def list_holds():
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    items = domain.rows(db.holds)
    for key in ("movement_id", "port_id", "hold_type", "status"):
        value = request.args.get(key)
        if value is not None and value != "":
            items = [h for h in items if h[key] == value]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.hold_json(h) for h in page], limit, offset, total)


@bp.route("/in-bond/examination-holds/<hold_id>/release", methods=["POST"])
def release_hold(hold_id):
    user_id, _role = require("CBPOfficer")

    # Band 4 - the officer who placed a hold may not release it.
    rec = db.holds.get(hold_id)
    if rec is not None and rec["placed_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    body = v.get_body()
    findings_code = v.req_enum(body, "findings_code", FINDINGS_CODES)
    discrepancy_pieces = v.opt_int(body, "discrepancy_pieces", minimum=0)

    if rec is None:
        raise ApiError("ERR_HOLD_NOT_FOUND")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_HOLD_INVALID_STATE")

    rec["status"] = "RELEASED"
    rec["released_at"] = db.now
    rec["findings_code"] = findings_code
    rec["discrepancy_pieces"] = discrepancy_pieces if discrepancy_pieces is not None else 0
    touch(rec)
    domain.recompute_port(db.ports.get(rec["port_id"]))

    movement = db.movements.get(rec["movement_id"])
    if movement is not None and not domain.open_holds(movement["id"]):
        if movement["custody_status"] == "EXAM_HOLD":
            movement["custody_status"] = "BONDED"
            touch(movement)
        domain.close_if_exported(movement)
    return ok(domain.hold_json(rec))
