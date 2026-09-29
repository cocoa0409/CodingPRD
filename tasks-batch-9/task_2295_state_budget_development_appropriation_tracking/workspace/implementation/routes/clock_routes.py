"""The logical clock control surface used by the test harness."""

from flask import Blueprint

import auth
import clock
import db
import response
from services import core
from validators import body_json, read_instant

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.authenticate((auth.SYSTEM_ADMIN,))
    body = body_json()
    instant = read_instant(body, "to_iso8601")
    clock.set_now(instant)

    # the derived cycle quarter moved, so every quarter-dependent cycle figure
    # (projected cash, utilisation, posture and the release holds it drives)
    # has to settle again
    for cycle in db.sort_rows(list(db.budget_cycles.values())):
        core.sync(cycle)

    return response.ok({"current_utc": clock.now_iso()})
