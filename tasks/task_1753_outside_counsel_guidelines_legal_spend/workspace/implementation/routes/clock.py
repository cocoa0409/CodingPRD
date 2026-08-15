"""Logical clock test-driving endpoint (PRD §2.5)."""

from flask import Blueprint

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS
from services import invoice_service as svc

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_auth([ROLE_LEGAL_OPS])
    body = helpers.get_body()
    helpers.require_fields(body, ["to_iso8601"])
    target = db.parse_iso(body.get("to_iso8601"))
    if target is None:
        raise errors.invalid_temporal("to_iso8601 is not a valid ISO-8601 instant")
    db.set_clock(target)
    # System clock sweep: flip overdue PENDING acknowledgments to OVERDUE.
    svc.sweep_overdue_acknowledgments()
    return resp.success_object({"current_utc": db.format_iso(db.get_clock())})
