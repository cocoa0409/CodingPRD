from flask import Blueprint

import core
import gates
from core import fail, fmt_iso, now, parse_iso

bp = Blueprint("system", __name__)


@bp.post("/property-care/_clock/set_current_utc")
def set_clock():
    gates.begin(["PlatformAdmin"])
    body = gates.body_json()
    gates.validate_payload(body, [("to_iso8601", "datetime", True)])
    target = parse_iso(body["to_iso8601"])
    if target < now():
        fail("ERR_CLOCK_REGRESSION", "The logical clock is monotonic.")
    core.set_clock(target)
    return core.ok({"current_utc": fmt_iso(now())})


@bp.get("/property-care/_clock")
def read_clock():
    gates.begin(["PlatformAdmin", "Auditor", "AccountManager", "Dispatcher", "StormCoordinator"])
    return core.ok({"current_utc": fmt_iso(now())})
