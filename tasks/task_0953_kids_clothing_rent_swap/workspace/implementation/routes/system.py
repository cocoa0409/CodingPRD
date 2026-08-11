"""The logical-clock test-driving capability."""

from flask import Blueprint

import auth
import envelope
import shape
import timeutil

bp = Blueprint("system", __name__)


@bp.post("/kidswear/_clock/set_current_utc")
def set_clock():
    auth.gate("PlatformAdmin")
    body = shape.body_json()
    moment = shape.instant(body, "to_iso8601")
    timeutil.clock.set(moment)
    return envelope.ok({"current_utc": timeutil.render_instant(timeutil.now())})
