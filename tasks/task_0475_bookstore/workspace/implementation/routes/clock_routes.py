"""Logical clock administration (PRD §3.1)."""
from flask import Blueprint

from clock import clock
from common import json_body
from datetime_util import parse_iso8601
from errors import err, ERR_INVALID_REQUEST
from middleware import authorize
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # No auth headers required (PRD §2.1 exception); role must still be StoreAdmin
    # if provided. The clock-set capability is administrative; the validations
    # table lists it among the two no-auth endpoints. We accept it without auth.
    body = json_body(optional=False)
    value = body.get("to_iso8601")
    if value is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    dt = parse_iso8601(value)
    clock.set(dt)
    return success_object({}, status=200)


# Suppress unused import warning
_ = authorize
