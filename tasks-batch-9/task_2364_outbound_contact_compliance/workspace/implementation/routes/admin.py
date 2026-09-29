"""The two test-driving administrative endpoints (PRD §2.5)."""

from flask import Blueprint

import validation as v
from db import db
from middleware import endpoint, payload
from response import created, ok
from util import parse_dt

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_clock():
    body = payload()
    raw = v.require(body, "to_iso8601")
    parsed = parse_dt(raw) if isinstance(raw, str) else None
    if parsed is None:
        v.bad("Field 'to_iso8601' must be an ISO 8601 timestamp.")
    db.clock = parsed
    from db import now_iso

    return ok({"current_utc": now_iso()})


@bp.post("/_rnd/records")
@endpoint(["PlatformAdmin"])
def seed_rnd():
    body = payload()
    phone_number = v.req_phone(body, "phone_number")
    reassigned_on = v.req_date(body, "reassigned_on")
    db.rnd_records[phone_number] = reassigned_on
    return created({"phone_number": phone_number, "reassigned_on": reassigned_on})
