"""Line endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_int, make_entity, lookup, list_response, public,
)
from response import success_object
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("lines", __name__)


@bp.route("/bakery/lines", methods=["POST"])
def create_line():
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    data = body()
    plant_id = req_string(data, "plant_id")
    lookup(DB.plants, plant_id, "plant")
    line_code = req_string(data, "line_code")
    hourly_capacity_units = req_int(data, "hourly_capacity_units", min_value=1)

    for ln in DB.lines.values():
        if ln.get("plant_id") == plant_id and ln.get("line_code") == line_code:
            raise ApiError(ERR_INVALID_REQUEST, f"line_code {line_code} already exists in plant", 400)

    line = make_entity({
        "plant_id": plant_id,
        "line_code": line_code,
        "hourly_capacity_units": hourly_capacity_units,
        "cleanliness": "CLEAN",
        "allergen_class_current": "NONE",
    })
    DB.lines[line["id"]] = line
    return success_object(public(line), status=201)


@bp.route("/bakery/lines/<lid>", methods=["GET"])
def get_line(lid):
    get_auth()
    line = lookup(DB.lines, lid, "line")
    return success_object(public(line))


@bp.route("/bakery/lines", methods=["GET"])
def list_lines():
    get_auth()
    filters = {"plant_id": request.args.get("plant_id")}
    return list_response(list(DB.lines.values()), filters)
