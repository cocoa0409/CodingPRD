"""The logical registry clock (PRD 2.4 and 3.1).

Setting the clock fires no state transition of its own; expiries are realised
only by the posture recalculation sweep or by a request that itself carries a
temporal precondition.
"""

from flask import Blueprint

import clock
import envelope
import validation as v

bp = Blueprint("clock", __name__)

SET_ROLES = ["PlatformAdmin", "ConverterSponsor", "StateRegulator",
             "EscrowAgent", "LenderUnderwriter"]
READ_ROLES = list(v.ROLES)


def _render(instant):
    """The clock's own rendering: whole seconds when the instant carries no
    fractional part, so a freshly booted server reads 2026-08-01T00:00:00Z."""
    if instant.microsecond == 0:
        return instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    return clock.format_instant(instant)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    v.authorize(SET_ROLES)
    body = v.parse([v.field("current_utc", "datetime")])
    clock.CLOCK.set(body["current_utc"])
    return envelope.object_response({"current_utc": _render(clock.now())}, 200)


@bp.get("/_clock/current")
def get_current_utc():
    v.authorize(READ_ROLES)
    return envelope.object_response({"current_utc": _render(clock.now())}, 200)
