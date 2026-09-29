"""The logical shop clock (PRD section 2.5)."""

from flask import Blueprint

import db
import validation as v
from middleware import authenticate_clock
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/tooling/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate_clock()
    payload = v.body(required=("current_utc",))
    dt = v.as_datetime(payload, "current_utc")
    db.set_clock(payload["current_utc"], dt)
    return object_response({"current_utc": payload["current_utc"]})
