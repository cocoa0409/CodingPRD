"""The logical clock capability (PRD 2.5)."""

from flask import Blueprint

from envelope import ok
from ladder import begin, req_instant
from store import clock

bp = Blueprint("misc", __name__)
PREFIX = "/smart-home-support"


@bp.post(PREFIX + "/_clock/set_current_utc")
def set_clock():
    """Setting the clock performs no state transitions of its own: no ticket
    breaches, no window closes and no campaign halts merely because time
    moved.  Those consequences are realised only when a subsequent request
    evaluates the rule in question.

    The clock capability is exempt from every gate.
    """
    ctx = begin(("PlatformAdmin",))
    raw, dt = req_instant(ctx.body, "to_iso8601")
    clock.set(dt, raw)
    # current_utc carries the clock's new value, i.e. the instant the caller
    # supplied, echoed verbatim (G2).
    return ok({"current_utc": clock.raw()})
