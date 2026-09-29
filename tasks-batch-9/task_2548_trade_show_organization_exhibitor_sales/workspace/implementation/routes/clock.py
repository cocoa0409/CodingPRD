"""The logical clock: the only test-driving capability (PRD 2.4)."""
from flask import Blueprint

import validate
from db import set_clock
from middleware import ALL_ROLES, authenticate
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    body = validate.body()
    current_utc = validate.datetime_field(body, "current_utc")
    authenticate(ALL_ROLES)
    set_clock(current_utc)
    return object_response({})
