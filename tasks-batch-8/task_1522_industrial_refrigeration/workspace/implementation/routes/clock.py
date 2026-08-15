"""The logical clock (PRD 2.5)."""
from flask import Blueprint

import envelope
from guards import endpoint, req_instant
from store import db
from util import iso

bp = Blueprint("clock", __name__)

SCHEMA = (frozenset(["to_iso8601"]), frozenset(["to_iso8601"]))


@bp.post("/psm/_clock/set_current_utc")
@endpoint(["FacilityAdmin", "ComplianceOfficer"], schema=SCHEMA)
def set_clock(ctx):
    instant = req_instant(ctx.body, "to_iso8601")
    db.set_clock(instant)
    return envelope.ok({"current_utc": iso(db.now())})
