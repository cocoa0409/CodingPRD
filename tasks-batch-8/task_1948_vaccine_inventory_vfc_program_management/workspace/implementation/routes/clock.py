"""Logical clock endpoint (PRD §2.10)."""

from flask import Blueprint, request

import db
from middleware import get_auth, ROLE_COMPLIANCE_AUDITOR
from response import success_object
from services.ledger import run_expiration_sweep
from services.validate import require_body, require_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    body = require_body(request.get_json(silent=True))
    _, dt = require_datetime(body, "to_iso8601")
    db.set_logical_clock(dt)
    run_expiration_sweep()
    return success_object({"current_utc": db.get_logical_now_iso()})
