"""Registers (PRD 3.8)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from routes.helpers import list_from, list_response, public
from services.core import new_record
from validate import get_body, req_int, req_str, require_path_resource

bp = Blueprint("registers", __name__)

READ_ROLES = ["GeneralManager", "ShiftManager"]


@bp.post("/sites/<sid>/registers")
def create_register(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    code = req_str(body, "register_code")
    float_cents = req_int(body, "float_cents", non_negative=True)
    for r in db["registers"].values():
        if r["site_id"] == site["id"] and r["register_code"] == code:
            raise_error(ERR_INVALID_REQUEST, "register_code must be unique within the site")
    rec = new_record("registers", {
        "site_id": site["id"],
        "register_code": code,
        "float_cents": float_cents,
        "posture": "OK",
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/registers")
def list_registers(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    return list_response("registers", {"site_id": sid})


@bp.get("/registers/<rid>")
def get_register(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("registers", rid)
    return success_object(public(rec))


@bp.get("/registers/<rid>/shifts")
def register_shifts(rid):
    authorized(READ_ROLES)
    reg = require_path_resource("registers", rid)
    shifts = [s for s in db["shifts"].values() if s["register_id"] == reg["id"]]
    return list_from(shifts)


@bp.get("/registers/<rid>/cash-drops")
def register_cash_drops(rid):
    authorized(READ_ROLES)
    reg = require_path_resource("registers", rid)
    drops = [d for d in db["cash_drops"].values() if d["register_id"] == reg["id"]]
    return list_from(drops)


@bp.get("/registers/<rid>/safe-deposits")
def register_safe_deposits(rid):
    authorized(READ_ROLES)
    reg = require_path_resource("registers", rid)
    deposits = [d for d in db["safe_deposits"].values() if d["register_id"] == reg["id"]]
    return list_from(deposits)
