"""The logical clock test capability (PRD section 2.4)."""

from flask import Blueprint

from db import db
from middleware import ALL_ROLES, authenticate
from response import object_response
from validation import body_json, field_timestamp

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/gpo/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # The sole endpoint that needs no user identity.
    authenticate(ALL_ROLES, require_identity=False)
    body = body_json()
    raw, moment = field_timestamp(body, "current_utc")
    db.set_clock(raw, moment)
    return object_response({"current_utc": db.clock_raw})
