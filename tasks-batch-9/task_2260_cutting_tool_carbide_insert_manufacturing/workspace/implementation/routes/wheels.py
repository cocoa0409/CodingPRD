"""Grinding wheels and dressing (PRD section 3.4)."""

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("wheels", __name__)

READ_ROLES = ["ProductionPlanner", "QualityApprover", "GeometryEngineer", "ApplicationEngineer"]
OWNER = ["ProductionPlanner"]


@bp.route("/tooling/grinding-wheels", methods=["POST"])
def create():
    authenticate(OWNER)
    payload = v.body(required=("wheel_code", "spec_code", "initial_life_units"))
    wheel_code = v.as_string(payload, "wheel_code")
    spec_code = v.as_string(payload, "spec_code")
    life = v.as_int(payload, "initial_life_units", minimum=100, maximum=100000)

    derive.require_unique("wheels", "wheel_code", wheel_code)

    row = db.new_row(
        {
            "wheel_code": wheel_code,
            "spec_code": spec_code,
            "initial_life_units": life,
            "consumed_life_units": 0,
            "dress_count": 0,
            "status": "AVAILABLE",
        }
    )
    db.wheels[row["id"]] = row
    return object_response(serialize.wheel(row), 201)


@bp.route("/tooling/grinding-wheels", methods=["GET"])
def index():
    rows, limit, offset = c.listing("wheels", READ_ROLES, {"status": c.WHEEL_STATUSES})
    return c.list_response("wheels", rows, limit, offset)


@bp.route("/tooling/grinding-wheels/<wheel_id>", methods=["GET"])
def read(wheel_id):
    return c.read_one("wheels", wheel_id, READ_ROLES)


@bp.route("/tooling/grinding-wheels/<wheel_id>/dress", methods=["POST"])
def dress(wheel_id):
    authenticate(OWNER)
    payload = v.body(optional=("dress_note",))
    v.as_string(payload, "dress_note", nullable=True)

    wheel = derive.must_exist("wheels", wheel_id)
    if wheel["status"] != "DRESSING":
        raise ApiError(
            "ERR_INVALID_WHEEL_STATE",
            "Only a wheel at DRESSING may be dressed (currently %s)." % wheel["status"],
        )

    if wheel["dress_count"] + 1 <= calc.MAX_DRESS_COUNT:
        wheel["status"] = "AVAILABLE"
        wheel["consumed_life_units"] = 0
    else:
        wheel["status"] = "EXPIRED"
    wheel["dress_count"] = wheel["dress_count"] + 1
    db.touch(wheel)
    return object_response(serialize.wheel(wheel))
