"""The logical-clock test-driving capability (PRD 2.5)."""

from flask import Blueprint

import clock
import guards
import response

bp = Blueprint("clock_routes", __name__)


@bp.route("/compliance/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    guards.authorize("PlatformOperator")
    body = guards.read_body()
    current_utc = guards.field(body, "current_utc", "datetime")
    wanted = clock.parse_datetime(current_utc)
    # Ladder step 45 — the clock is monotonic.
    guards.require(
        wanted >= clock.now(),
        "ERR_CLOCK_REWIND_FORBIDDEN",
        "The logical clock may only move forward or hold; it currently reads %s."
        % clock.now_iso(),
    )
    clock.set_now(wanted)
    return response.object_response({"current_utc": clock.now_iso()})
