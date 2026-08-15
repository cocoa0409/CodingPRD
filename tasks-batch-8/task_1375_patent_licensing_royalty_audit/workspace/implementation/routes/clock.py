"""Logical clock endpoint (IPAdmin only)."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response
from services import calc

bp = Blueprint("clock", __name__)


@bp.post("/licensing/_clock/set_current_utc")
def set_current_utc():
    middleware.require_role("IPAdmin")
    body = common.get_body()
    common.validate_body(body, [("to_iso8601", "datetime", True)])
    new_dt = common.parse_dt(body["to_iso8601"])
    db.current_utc = common.fmt_dt(new_dt)

    # Sweep 1: expire ACTIVE/SUSPENDED agreements past expiration_date
    for agr in db.agreements.values():
        if agr["status"] in ("ACTIVE", "SUSPENDED") and \
                common.parse_dt(agr["expiration_date"]) < new_dt:
            agr["status"] = "EXPIRED"
            common.touch(agr)

    # Sweep 2: achieve due DATE milestones (per agreement creation order)
    due = [
        m for m in db.milestones.values()
        if m["status"] == "PENDING"
        and m["trigger_type"] == "DATE"
        and common.parse_dt(m["trigger_date"]) <= new_dt
    ]
    due.sort(key=lambda m: (m["created_at"], m["id"]))
    for m in due:
        calc.achieve_milestone(m)

    return response.success_object({"current_utc": db.current_utc})
