"""Logical clock endpoints (PRD §2.4)."""
from flask import Blueprint

import db
import validation as v
from middleware import ALL_ROLES, authenticate
from response import iso, object_response

bp = Blueprint("clock", __name__)


@bp.route("/vpc/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(ALL_ROLES)
    body = v.body()
    instant = v.req_instant(body, "current_utc")
    db.clock_set(instant)
    return object_response({"current_utc": iso(instant)})


@bp.route("/vpc/_clock", methods=["GET"])
def read_clock():
    authenticate(ALL_ROLES)
    return object_response({"current_utc": iso(db.clock_now())})
