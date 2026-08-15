"""Test-driving logical clock (PRD 2.4)."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from services import sweep
from util import CLOCK
from routes.helpers import body

bp = Blueprint("clock", __name__)


@bp.post("/roofing/_clock/set_current_utc")
def set_current_utc():
    authorized(["PlatformAdmin"])
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if not to_iso8601:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 is required")
    CLOCK.set(to_iso8601)
    # Every advance re-evaluates all time-dependent system transitions.
    sweep.sweep()
    return success_object({"current_utc": CLOCK.now_iso()})
