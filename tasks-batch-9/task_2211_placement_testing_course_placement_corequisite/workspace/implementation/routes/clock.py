"""POST /_clock/set_current_utc -- the logical clock and its single sweep."""

from flask import Blueprint

from db import db, sort_rows, touch
from middleware import authenticate
from response import iso, ok
from services import calc
from validators import Field, parse_body

bp = Blueprint("clock", __name__)

SPEC = {"current_utc": Field("datetime", required=True)}


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("SystemAdmin",))
    body = parse_body(SPEC)
    db.clock = body["current_utc"]

    # PRD 2.5: exactly one sweep and nothing else.
    expired = []
    for override in sort_rows(list(db.overrides.values())):
        if override["state"] == "ISSUED" and override["expires_at"] <= db.clock:
            override["state"] = "EXPIRED"
            touch(override)
            expired.append(override["id"])
    if expired:
        for reg in sort_rows(list(db.registrations.values())):
            if reg["state"] in ("PENDING", "WAITLISTED") and reg["override_id"] in expired:
                calc.recompute_registration_prerequisite(reg)

    return ok({"current_utc": iso(db.clock)})
