"""Logical clock endpoint (PRD 2.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/household-payroll/_clock/set_current_utc", methods=["POST"])
@require_roles("PayrollAdmin")
def set_clock(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = parse_iso8601(require_field(body, "to_iso8601"), "to_iso8601")
    db.set_current_utc(to_iso8601)

    # Policy sweeps: BOUND -> ACTIVE once coverage_start is reached;
    # ACTIVE -> EXPIRED once coverage_end has passed.
    today = db.clock_today()
    for pol in db.policies.values():
        if pol["status"] == "BOUND" and today >= pol["coverage_start"]:
            pol["status"] = "ACTIVE"
            db.touch(pol)
        elif pol["status"] == "ACTIVE" and today > pol["coverage_end"]:
            pol["status"] = "EXPIRED"
            db.touch(pol)

    return success_object({"current_utc": db.get_current_utc()})
