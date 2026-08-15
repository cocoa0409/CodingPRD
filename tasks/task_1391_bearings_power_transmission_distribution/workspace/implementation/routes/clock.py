"""POST /motion/_clock/set_current_utc — advance the logical clock."""

from flask import Blueprint

import transitions
from db import store
from helpers import get_body, now, render_dt
from middleware import require_roles
from response import ok
from helpers import req_dt

bp = Blueprint("clock", __name__)


@bp.route("/motion/_clock/set_current_utc", methods=["POST"])
@require_roles("SystemAdmin")
def set_clock(user_id, role):
    body = get_body()
    to = req_dt(body, "to_iso8601")
    store.clock = to
    transitions.run_scheduled_transitions()
    return ok({"current_utc": render_dt(now())})
