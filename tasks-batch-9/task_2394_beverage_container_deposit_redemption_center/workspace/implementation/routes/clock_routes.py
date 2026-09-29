from flask import Blueprint, request

import clock
import response
import validation as v
from errors import fail
from middleware import ROLES

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # Reachable without headers for harness bootstrapping, but a role that is
    # supplied must be recognised, and only a ProgramAdmin may move the clock.
    role = (request.headers.get("X-User-Role") or "").strip()
    if role:
        if role not in ROLES:
            fail("ERR_UNAUTHENTICATED", "X-User-Role does not name a recognised role.")
        if role != "ProgramAdmin":
            fail("ERR_UNAUTHORIZED", "Only a ProgramAdmin may set the logical clock.")
    body = v.body()
    raw = v.req_str(body, "to_iso8601")
    parsed = clock.parse_iso(raw)
    if parsed is None:
        v.bad("Field 'to_iso8601' must be an ISO 8601 instant.")
    clock.set_now(parsed)
    return response.obj({})
