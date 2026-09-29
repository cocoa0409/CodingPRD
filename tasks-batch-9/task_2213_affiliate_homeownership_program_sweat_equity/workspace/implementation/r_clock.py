"""The logical UTC clock. The only path callable without auth headers."""
from flask import Blueprint, request

import cascade
from common import okay
from errors import fail
from payload import body, vdatetime
from rbac import ALL_ROLES
from store import db
from util import iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role = request.headers.get("X-User-Role")
    if role:
        if role not in ALL_ROLES:
            fail("ERR_UNKNOWN_ROLE")
        if role != "ProgramAdmin":
            fail("ERR_ROLE_NOT_PERMITTED")

    data = body()
    target = vdatetime(data, "current_utc", required=True,
                       aliases=("to_iso8601", "current_utc_iso8601", "now"))

    if target <= db.clock:
        fail("ERR_CLOCK_MUST_ADVANCE")

    db.clock = target
    cascade.clock_cascade()
    return okay({"current_utc": iso(db.clock)})
