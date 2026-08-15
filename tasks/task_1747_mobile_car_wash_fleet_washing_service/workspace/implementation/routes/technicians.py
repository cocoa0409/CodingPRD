"""Technician endpoints."""

from flask import Blueprint

from db import store
from serialize import ser_technician
from util import (
    caller, require_role, get_body, respond, req_str, opt_bool, stamp_new,
    touch, ApiError,
)
from errors import ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE

bp = Blueprint("technicians", __name__)


@bp.post("/fleet-wash/technicians")
def create_technician():
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    certified = opt_bool(body, "water_reclaim_certified", False)
    rec = {
        "name": name,
        "water_reclaim_certified": certified,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    store.technicians[rec["id"]] = rec
    return respond(ser_technician(rec), 201)


@bp.get("/fleet-wash/technicians/<tid>")
def get_technician(tid):
    _uid, _role = caller()
    rec = store.technicians.get(tid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Technician %s not found" % tid)
    return respond(ser_technician(rec), 200)


@bp.post("/fleet-wash/technicians/<tid>/events")
def technician_event(tid):
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    rec = store.technicians.get(tid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Technician %s not found" % tid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("DEACTIVATE", "REACTIVATE", "CERTIFY_RECLAIM"):
        raise ApiError(ERR_VALIDATION,
                       "event_type must be DEACTIVATE, REACTIVATE, or CERTIFY_RECLAIM")
    if event == "DEACTIVATE":
        if rec["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Technician is not ACTIVE")
        rec["status"] = "INACTIVE"
    elif event == "REACTIVATE":
        if rec["status"] != "INACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Technician is not INACTIVE")
        rec["status"] = "ACTIVE"
    else:  # CERTIFY_RECLAIM
        if rec["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Technician is not ACTIVE")
        rec["water_reclaim_certified"] = True
    touch(rec)
    return respond(ser_technician(rec), 200)
