"""The logical clock and the ops-run checkpoint."""

import envelope
import timeutil
from dispatch import endpoint
from errors import ApiError
from services import opsrun
from timeutil import CLOCK


@endpoint("POST", "/_clock/set_current_utc", roles=["PlatformAdmin"], success_code=200)
def set_clock(context):
    target = context.body.instant("to_iso8601", required=True)  # rung 13
    if target < CLOCK.now():  # rung 17
        raise ApiError("ERR_CLOCK_REGRESSION")
    previous = CLOCK.set(target)
    # Both instants pass through THE single renderer, so a caller-supplied
    # instant is normalised to the server's rendering (3 fractional digits,
    # 'Z'), never echoed verbatim.
    return envelope.object_response(
        {
            "current_utc": timeutil.render_instant(CLOCK.now()),
            "previous_utc": timeutil.render_instant(previous),
        }
    )


@endpoint("POST", "/_ops/advance-calendar", roles=["PlatformAdmin"], success_code=200)
def advance_calendar(context):
    return envelope.object_response(opsrun.run())
