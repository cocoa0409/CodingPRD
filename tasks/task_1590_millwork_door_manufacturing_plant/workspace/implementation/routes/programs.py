"""MachiningProgram endpoints (PRD §3.4)."""

import uuid

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_int, require_existence)
from response import success, list_response, parse_pagination
from services import cascade

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = ("CREATED", "SETUP_BOOKED", "PROVEN", "RELEASED", "VOIDED")


def serialize(p):
    return {
        "id": p["id"],
        "drawing_id": p["drawing_id"],
        "order_id": p["order_id"],
        "program_code": p["program_code"],
        "estimated_minutes": p["estimated_minutes"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/machining-programs")
def create_program():
    _, role = get_context()
    require_role(role, "ProductionLead")
    body = raw_body()
    # Rung 3: body FK existence in declared input order.
    if body.get("drawing_id") is not None:
        drawing = require_existence(db.shop_drawings, body["drawing_id"],
                                    "ERR_DRAWING_NOT_FOUND", "ShopDrawing")
    else:
        drawing = None
    if body.get("order_id") is not None:
        require_existence(db.orders, body["order_id"], "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    # Rung 4: payload.
    validate_fields(body, required=("drawing_id", "order_id", "estimated_minutes"))
    estimated_minutes = req_int(body, "estimated_minutes")
    # Rung 6: the referenced drawing must be APPROVED.
    if drawing["status"] != "APPROVED":
        raise err("ERR_DRAWING_NOT_APPROVED", "Program creation requires an APPROVED drawing")
    # Rung 8: payload order must equal the drawing's order.
    if body["order_id"] != drawing["order_id"]:
        raise err("ERR_PROGRAM_ORDER_MISMATCH", "Payload order_id != drawing.order_id")
    rec = db.new_record()
    rec.update({
        "drawing_id": drawing["id"],
        "order_id": body["order_id"],
        "program_code": "PROG-" + uuid.uuid4().hex[:8].upper(),
        "estimated_minutes": estimated_minutes,
        "status": "CREATED",
    })
    db.machining_programs[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/machining-programs")
def list_programs():
    get_context()
    limit, offset = parse_pagination(request.args)
    drawing_id = request.args.get("drawing_id")
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    items = [p for p in db.machining_programs.values()
             if (drawing_id is None or p["drawing_id"] == drawing_id)
             and (order_id is None or p["order_id"] == order_id)
             and (status is None or p["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/machining-programs/<pid>")
def get_program(pid):
    get_context()
    program = require_existence(db.machining_programs, pid, "ERR_PROGRAM_NOT_FOUND", "MachiningProgram")
    return success(serialize(program))


@bp.put("/machining-programs/<pid>/status")
def transition_program(pid):
    _, role = get_context()
    require_role(role, "ProductionLead")
    program = require_existence(db.machining_programs, pid, "ERR_PROGRAM_NOT_FOUND", "MachiningProgram")
    body = raw_body()
    validate_fields(body, required=("target_status",))
    target = req_string(body, "target_status")
    current = program["status"]

    if target == "RELEASED":
        if current != "PROVEN":
            raise err("ERR_INVALID_PROGRAM_STATUS_TRANSITION",
                      "Program cannot transition from %s to RELEASED" % current)
        drawing = db.shop_drawings.get(program["drawing_id"])
        if drawing is None or drawing["status"] != "APPROVED":
            raise err("ERR_DRAWING_NOT_APPROVED", "Release requires drawing APPROVED")
        program["status"] = "RELEASED"

    elif target in ("VOID", "VOIDED"):
        if current not in ("CREATED", "SETUP_BOOKED", "PROVEN"):
            raise err("ERR_INVALID_PROGRAM_STATUS_TRANSITION",
                      "Program cannot transition from %s to VOIDED" % current)
        cascade.cancel_program_slots(program)
        program["status"] = "VOIDED"

    elif target in PROGRAM_STATUSES:
        raise err("ERR_INVALID_PROGRAM_STATUS_TRANSITION",
                  "Program cannot transition from %s to %s" % (current, target))
    else:
        raise err("ERR_INVALID_PROGRAM_STATUS_TRANSITION",
                  "Unknown program status: %s" % target)

    db.touch(program)
    return success(serialize(program))
