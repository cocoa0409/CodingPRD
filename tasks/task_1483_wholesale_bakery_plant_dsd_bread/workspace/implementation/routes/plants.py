"""Plant endpoints."""

from flask import Blueprint

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_number, make_entity, touch, lookup, list_response, public,
)
from response import success_object
from services.cascades import close_day_sweeps

bp = Blueprint("plants", __name__)


@bp.route("/bakery/plants", methods=["POST"])
def create_plant():
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    data = body()
    name = req_string(data, "name")
    baseline_flour_index = req_number(data, "baseline_flour_index")
    baseline_butter_index = req_number(data, "baseline_butter_index")

    plant = make_entity({
        "name": name,
        "baseline_flour_index": baseline_flour_index,
        "baseline_butter_index": baseline_butter_index,
        "day_index": 0,
    })
    DB.plants[plant["id"]] = plant
    return success_object(public(plant), status=201)


@bp.route("/bakery/plants/<pid>", methods=["GET"])
def get_plant(pid):
    get_auth()
    plant = lookup(DB.plants, pid, "plant")
    return success_object(public(plant))


@bp.route("/bakery/plants", methods=["GET"])
def list_plants():
    get_auth()
    return list_response(list(DB.plants.values()))


@bp.route("/bakery/plants/<pid>/close_day", methods=["POST"])
def close_day(pid):
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    plant = lookup(DB.plants, pid, "plant")
    plant["day_index"] = int(plant.get("day_index") or 0) + 1
    touch(plant)
    close_day_sweeps(plant)
    return success_object(public(plant))
