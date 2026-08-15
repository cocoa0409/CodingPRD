"""Unit endpoints."""

from flask import Blueprint

from db import store, clock
from errors import ApiError, ERR_UNIT_NOT_FOUND, ERR_UNIT_NUMBER_EXISTS
from helpers import body, req_string, new_id, serialize_unit
from middleware import get_actor, require_role
from response import success_object

bp = Blueprint("units", __name__)

READ_ROLES = {"PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor"}


@bp.route("/v1/units", methods=["POST"])
def create_unit():
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    data = body()
    unit_number = req_string(data, "unit_number")
    building_code = req_string(data, "building_code")
    for u in store.units.values():
        if u["unit_number"] == unit_number:
            raise ApiError(ERR_UNIT_NUMBER_EXISTS, "unit_number already registered", 409)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "unit_number": unit_number,
        "building_code": building_code,
        "habitability_status": "HABITABLE",
        "_seq": store.next_seq(),
    }
    store.units[rec["id"]] = rec
    return success_object(serialize_unit(rec), 201)


@bp.route("/v1/units/<unitId>", methods=["GET"])
def get_unit(unitId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = store.units.get(unitId)
    if rec is None:
        raise ApiError(ERR_UNIT_NOT_FOUND, "Unit not found", 404)
    return success_object(serialize_unit(rec))
