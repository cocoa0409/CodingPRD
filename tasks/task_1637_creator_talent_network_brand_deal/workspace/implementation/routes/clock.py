"""PlatformAdmin logical clock endpoint: set the clock and run sweeps."""

from flask import Blueprint

import db
import response as resp
from middleware import require_roles
from services import clock as clock_svc
from services import helpers as H

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc(actor):
    payload = H.body()
    H.req_fields(payload, ["to_iso8601"])
    to = H.require_dt(payload, "to_iso8601")
    db.set_clock(to)
    clock_svc.sweep()
    return resp.ok({"current_utc": db.iso_format(db.get_clock())})
