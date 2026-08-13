"""DiningHall endpoints."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    SERVICE_MODELS,
    get_hall,
    has_open_critical_action,
    ser,
    stamp,
    suspend_hall,
    touch,
)
from util import as_enum, as_int, as_str, body, required
from routes.common import list_endpoint

bp = Blueprint("halls", __name__)


@bp.post("/dining-halls")
def create_hall():
    auth(["DiningAdmin"])
    data = body()
    name = as_str(required(data, "name"), "name")
    service_model = as_enum(required(data, "service_model"), "service_model", SERVICE_MODELS)
    dining_capacity = as_int(required(data, "dining_capacity"), "dining_capacity")
    if dining_capacity <= 0:
        raise ApiError("ERR_VALIDATION", 400, "dining_capacity must be > 0")
    catering_kitchen_capacity = as_int(
        required(data, "catering_kitchen_capacity"), "catering_kitchen_capacity"
    )
    if catering_kitchen_capacity <= 0:
        raise ApiError("ERR_VALIDATION", 400, "catering_kitchen_capacity must be > 0")
    rec = {
        "id": new_id(),
        "name": name,
        "service_model": service_model,
        "dining_capacity": dining_capacity,
        "catering_kitchen_capacity": catering_kitchen_capacity,
        "status": "ACTIVE",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["dining_halls"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/dining-halls")
def list_halls():
    return list_endpoint("dining_halls", [("status", "status")])


@bp.get("/dining-halls/<hid>")
def get_one_hall(hid):
    auth(ALL_ROLES)
    return ok(ser(get_hall(hid)))


@bp.post("/dining-halls/<hid>/suspend")
def suspend(hid):
    auth(["DiningAdmin"])
    hall = get_hall(hid)
    if hall["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "DiningHall is not ACTIVE")
    suspend_hall(hall)
    return ok(ser(hall))


@bp.post("/dining-halls/<hid>/reactivate")
def reactivate(hid):
    auth(["DiningAdmin"])
    hall = get_hall(hid)
    if hall["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "DiningHall is not SUSPENDED")
    if has_open_critical_action(hall["id"]):
        raise ApiError(
            "ERR_CRITICAL_VIOLATION_OPEN",
            422,
            "A CRITICAL corrective action is still open at this hall",
        )
    hall["status"] = "ACTIVE"
    touch(hall)
    return ok(ser(hall))
