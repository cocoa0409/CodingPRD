"""POST /_clock/set_current_utc - the Scheduler-only logical-clock endpoint
(PRD 2.4)."""

from clock import clock, parse_instant
from middleware import endpoint
from routes.common import invalid, one
from validate import req_str


@endpoint("POST", "/_clock/set_current_utc", roles=["Scheduler"], code=200)
def set_current_utc(ctx):
    raw = req_str(ctx.body, "to_iso8601")
    dt = parse_instant(raw)
    if dt is None:
        invalid("to_iso8601 must be an ISO 8601 datetime string.")
    if dt <= clock.now:
        # The clock never moves backwards: the target must be strictly later
        # than the current value.
        invalid("to_iso8601 must be strictly later than the current clock value.")
    clock.set(dt, raw)
    return one({"current_utc": clock.raw})
