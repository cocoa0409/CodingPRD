"""Operatory endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_OPERATORY_NOT_FOUND, ERR_VALIDATION
from middleware import ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK
from response import ok_array, ok_object
from routes._helpers import apply_filters, guard
from services import common

bp = Blueprint("operatories", __name__)


@bp.post("/operatories")
def create_operatory():
    guard([ROLE_FRONT_DESK])
    body = common.get_json_body()
    common.require_fields(body, ["room_name"])
    room_name = common.require_string(body, "room_name")
    buffer = common.optional_int(body, "turnover_buffer_minutes", 15)
    if buffer < 0:
        raise APIError(ERR_VALIDATION, 422, "turnover_buffer_minutes must be >= 0")
    rec = common.new_common_fields()
    rec.update({
        "room_name": room_name,
        "turnover_buffer_minutes": buffer,
        "status": "OPEN",
    })
    db.operatories[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/operatories")
def list_operatories():
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING])
    records = apply_filters(list(db.operatories.values()), {"status": request.args.get("status")})
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/operatories/<operatory_id>")
def get_operatory(operatory_id):
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING])
    rec = common.resolve(db.operatories, operatory_id, ERR_OPERATORY_NOT_FOUND)
    return ok_object(common.serialize(rec), 200)


@bp.post("/operatories/<operatory_id>/close")
def close_operatory(operatory_id):
    guard([ROLE_FRONT_DESK])
    rec = common.resolve(db.operatories, operatory_id, ERR_OPERATORY_NOT_FOUND)
    rec["status"] = "CLOSED"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)
