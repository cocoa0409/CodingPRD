"""POST /_clock/set_current_utc -- the logical clock."""

from flask import Blueprint

import db
import derive
import validators as v
from auth import authenticate
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(["PortalAdmin"])
    payload = v.body()
    instant = v.req_instant(payload, "to_iso8601")
    db.set_clock(instant)

    rescored = 0
    for contractor in db.ordered(db.contractors):
        if contractor["last_finding_at"] is not None:
            rescored += 1
            derive.recompute_contractor(contractor)

    return ok({"current_utc": db.iso(db.now()), "contractors_rescored": rescored})
