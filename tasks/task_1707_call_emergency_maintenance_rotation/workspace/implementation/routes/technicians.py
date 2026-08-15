"""Technician endpoints."""

from flask import Blueprint

from db import store, clock
from errors import (
    ApiError,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from helpers import (
    body,
    req_string,
    req_enum,
    req_int,
    new_id,
    serialize_technician,
    touch,
)
from middleware import get_actor, require_role
from response import success_object

bp = Blueprint("technicians", __name__)

CAPABILITIES = {"TECHNICIAN", "SUPERVISOR"}

READ_ROLES = {"PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor"}


@bp.route("/v1/technicians", methods=["POST"])
def create_technician():
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    data = body()
    full_name = req_string(data, "full_name")
    capability = req_enum(data, "capability", CAPABILITIES)
    base_rate = req_int(data, "base_hourly_rate_cents", minimum=1)
    diff_bp = req_int(data, "on_call_differential_bp", minimum=0)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "full_name": full_name,
        "capability": capability,
        "base_hourly_rate_cents": base_rate,
        "on_call_differential_bp": diff_bp,
        "status": "ACTIVE",
        "callback_minutes_168h": 0,
        "fatigue_block_until": None,
        "_seq": store.next_seq(),
    }
    store.technicians[rec["id"]] = rec
    return success_object(serialize_technician(rec), 201)


@bp.route("/v1/technicians/<technicianId>", methods=["GET"])
def get_technician(technicianId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = store.technicians.get(technicianId)
    if rec is None:
        raise ApiError(ERR_TECHNICIAN_NOT_FOUND, "Technician not found", 404)
    return success_object(serialize_technician(rec))


@bp.route("/v1/technicians/<technicianId>/deactivate", methods=["POST"])
def deactivate_technician(technicianId):
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    rec = store.technicians.get(technicianId)
    if rec is None:
        raise ApiError(ERR_TECHNICIAN_NOT_FOUND, "Technician not found", 404)
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_REQUEST, "Technician already inactive", 400)
    rec["status"] = "INACTIVE"
    touch(rec)
    return success_object(serialize_technician(rec))
