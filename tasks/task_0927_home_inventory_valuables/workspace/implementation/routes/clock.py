"""POST /_clock/set_current_utc - the administrative logical-clock endpoint."""

import derive
from registry import endpoint
from routes.common import one
from timeutil import clock, parse_instant


@endpoint(
    "POST",
    "/_clock/set_current_utc",
    roles=["PlatformAdmin"],
    code=200,
    body={"to_iso8601": ("datetime", True)},
)
def set_current_utc(ctx):
    raw = ctx.body["to_iso8601"]
    clock.set(parse_instant(raw), raw)
    counters = derive.hook_h1()
    payload = {"current_utc": clock.raw}  # PRD 2.5 rule 4: verbatim echo
    payload.update(counters)
    return one(payload)
