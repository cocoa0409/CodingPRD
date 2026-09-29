"""Logical clock and liveness probe."""

from flask import Blueprint

from db import store
from middleware import authenticate
from response import ok
from validate import body, instant_field

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("CorporateOps",))
    payload = body()
    raw, parsed = instant_field(payload, "current_utc", required=True)
    store.clock_raw = raw
    store.clock_dt = parsed
    return ok({"current_utc": store.clock_raw})


@bp.get("/_health")
def health():
    # The only endpoint in the API that does not require the identity headers.
    return ok({"status": "ok", "current_utc": store.clock_raw})
