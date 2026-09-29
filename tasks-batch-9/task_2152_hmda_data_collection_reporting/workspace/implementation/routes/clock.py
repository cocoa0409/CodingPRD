"""The logical clock test-driving surface (PRD 2.5)."""

from flask import Blueprint

import store
from auth import authenticate
from response import object_response
from validate import Field, check, json_body

bp = Blueprint("clock", __name__)

CLOCK_FIELDS = [Field("to_iso8601", "datetime", required=True)]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(["SystemAdmin"])
    body = check(json_body(), CLOCK_FIELDS)
    store.set_clock(body["to_iso8601"])
    return object_response({})
