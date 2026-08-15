"""Logical clock endpoint (test-driving capability)."""

from flask import Blueprint

from db import store
from errors import err, ERR_CLOCK_NOT_FORWARD
from middleware import auth, require_role, get_body, validate_payload, v_datetime
from response import ok
from util import iso_z

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    data = validate_payload(body, {"to_iso8601": (v_datetime, True, None)})
    _, role = auth()
    require_role(role, ["ProductionExecutive"])

    to_dt = data["to_iso8601"]
    if not to_dt > store.now():
        raise err(
            ERR_CLOCK_NOT_FORWARD,
            "to_iso8601 must be strictly greater than the current logical time",
            422,
        )
    store.set_clock(to_dt)
    return ok({"current_utc": iso_z(store.now())}, 200)
