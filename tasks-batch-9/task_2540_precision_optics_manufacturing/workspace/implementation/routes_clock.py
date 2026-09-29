"""The test-driving logical clock endpoint."""

from flask import Blueprint

from common import authenticate, get_body, ok, v_ts
from errors import ApiError
from store import store

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["PlantAdmin"])
    body = get_body()

    raw, dt = v_ts(body, "current_utc", True)

    # priority 27 — the logical clock never moves backwards; equality is admissible
    if dt < store.now_dt():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")

    previous = store.set_clock(raw, dt)
    return ok({"current_utc": raw, "previous_utc": previous})
