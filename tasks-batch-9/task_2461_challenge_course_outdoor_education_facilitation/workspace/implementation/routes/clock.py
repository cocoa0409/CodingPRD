"""The logical operating clock (PRD 2.4)."""
from flask import Blueprint

from db import store
from middleware import authorize, ALL_ROLES
from response import empty_response
from validation import body, req_instant

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # Reachable before any staff record exists, so identity is not resolved.
    authorize(ALL_ROLES, identity=False)
    payload = body()
    current_utc = req_instant(payload, "current_utc")

    # Setting the clock recomputes nothing: the passage of time becomes visible
    # only at the next write or daily-open checkpoint.
    store.clock = current_utc
    return empty_response()
