"""Driver endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, make_entity, lookup, list_response, public,
)
from response import success_object
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("drivers", __name__)


@bp.route("/bakery/drivers", methods=["POST"])
def create_driver():
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    data = body()
    plant_id = req_string(data, "plant_id")
    lookup(DB.plants, plant_id, "plant")
    name = req_string(data, "name")
    max_daily = data.get("max_daily_drive_minutes", 600)
    if max_daily is None:
        max_daily = 600
    if isinstance(max_daily, bool) or not isinstance(max_daily, int) or max_daily <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "max_daily_drive_minutes must be a positive integer", 400)

    driver = make_entity({
        "plant_id": plant_id,
        "name": name,
        "max_daily_drive_minutes": max_daily,
        "status": "ACTIVE",
        "shrink_liability_cents": 0,
    })
    DB.drivers[driver["id"]] = driver
    return success_object(public(driver), status=201)


@bp.route("/bakery/drivers/<did>", methods=["GET"])
def get_driver(did):
    get_auth()
    driver = lookup(DB.drivers, did, "driver")
    return success_object(public(driver))


@bp.route("/bakery/drivers", methods=["GET"])
def list_drivers():
    get_auth()
    filters = {"plant_id": request.args.get("plant_id")}
    return list_response(list(DB.drivers.values()), filters)
