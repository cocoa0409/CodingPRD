"""Test-driving clock + overdue sweep (PRD §3.8)."""
from flask import Blueprint

from db import db
from middleware import get_identity, require_roles, ROLE_FRONTDESK
from response import success
from common import get_json_body, require_fields, parse_iso8601, iso_from_dt


bp = Blueprint("clock", __name__)


@bp.post("/dojo/_clock/advance")
def advance_clock():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    new_dt = parse_iso8601(body["to_iso8601"])
    db.set_clock(new_dt)
    # The clock advance only moves the logical clock. The overdue transition
    # itself is performed per-invoice by POST /dojo/invoices/{id}/mark-overdue
    # (PRD §3.8: the sweep "can" move past-due invoices once the clock passes
    # their due_at). Keeping the two steps separate avoids surprising an
    # explicit mark-overdue with an already-swept invoice.
    return success({"current_utc": iso_from_dt(db.now())}, 200)
