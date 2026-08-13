"""Logical clock (PRD 2.5)."""
from flask import Blueprint

import errors
from db import store, fmt_instant
from errors import ApiError
from middleware import require_auth, get_body, parse_instant
from response import ok_object

bp = Blueprint("clock", __name__)


@bp.post("/tp/_clock/set_current_utc")
def set_current_utc():
    require_auth(["GroupTaxAdmin"])
    body = get_body()
    target = parse_instant(body.get("to_iso8601"))
    if target is None:
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "to_iso8601 is required and must be an ISO 8601 instant")
    if target < store.clock:
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "The logical clock is monotonic; setting it backwards is rejected")
    store.clock = target
    return ok_object({"current_utc": fmt_instant(store.clock)}, 200)
