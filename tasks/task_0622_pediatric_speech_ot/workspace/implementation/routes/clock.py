"""Logical clock control (PRD §2.11, §3.4)."""

from flask import Blueprint

from db import db
from response import success
from middleware import require_roles
from validation import get_body, require_str
from clock import parse_iso
from services import engine

bp = Blueprint("clock", __name__)


@bp.route("/clinic/_clock/set_current_utc", methods=["POST"])
@require_roles("ClinicAdmin")
def set_current_utc(user_id=None, role=None):
    body = get_body()
    # Input field is to_iso8601 (scaffold §1.5).
    value = require_str(body, "to_iso8601")
    try:
        parse_iso(value)
    except Exception:
        from validation import bad
        raise bad("to_iso8601 must be an ISO 8601 datetime.")
    db.clock.set(value)
    # Setting the clock triggers pending ACTIVE->EXPIRED auto-transitions.
    expired_ids = engine.expire_due_authorizations()
    return success({
        "current_utc": db.clock.now_iso(),
        "expired_authorization_ids": expired_ids,
    }, status=200)
