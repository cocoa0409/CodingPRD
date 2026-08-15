"""POST /_clock/set_current_utc - the logical-clock endpoint (PRD 2.4).

The clock never falls back to wall-clock time; it advances only when an
authorized caller moves it. Setting the clock triggers the breach escalation
sweep (PRD 3.5). The Regulator role cannot move the clock.
"""

from envelope import object_response
from errors import ApiError
from services import escalation_sweep
from timeutil import clock, parse_instant

from routes.common import endpoint


@endpoint("POST", "/_clock/set_current_utc",
          roles=["TreasuryAnalyst", "ModelRiskValidator", "ALCOChair"])
def set_current_utc(ctx):
    raw = ctx.body.get("to_iso8601")
    instant = parse_instant(raw) if isinstance(raw, str) else None
    if instant is None:
        raise ApiError("ERR_INVALID_REQUEST")
    clock.set(instant, raw)
    escalation_sweep()
    # current_utc reproduces the operator-supplied string verbatim.
    return object_response({"current_utc": clock.raw})
