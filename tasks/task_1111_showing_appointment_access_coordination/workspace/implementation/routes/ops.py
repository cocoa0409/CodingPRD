"""Platform ops: logical clock and expiration sweep."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from services import calc

bp = Blueprint("ops", __name__)


@bp.post("/showing-desk/_clock/set_current_utc")
def set_clock():
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "to_iso8601": ("datetime", True),
    })
    mw.require_roles(caller, ["PlatformAdmin"])
    clock.set_current(fields["to_iso8601"])
    return response.success_object({"current_utc": clock.fmt_minute(clock.now())})


@bp.post("/showing-desk/_ops/run_expiration_sweep")
def run_expiration_sweep():
    caller = mw.authenticate()
    mw.get_json_body(required=False)
    mw.require_roles(caller, ["PlatformAdmin"])
    counts = calc.run_sweep()
    return response.success_object(counts)
