"""Test-driving endpoints: /_clock/set (unauthenticated) and /_reminders/dispatch
(PlatformOperator) (PRD §3.8)."""
from flask import Blueprint

import clock
import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles

bp = Blueprint("testdriving", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    with db.lock:
        # unauthenticated allowed (PRD §2.1)
        body = validate.get_json_body()
        if "to_iso8601" not in body or body["to_iso8601"] is None:
            raise err("ERR_VALIDATION", "Missing required field: to_iso8601.")
        try:
            dt = clock.parse_iso8601(body["to_iso8601"])
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime.")
        db.set_clock(dt)
        return response.ok({})


@bp.route("/_reminders/dispatch", methods=["POST"])
def dispatch_reminders():
    with db.lock:
        p = authenticate()
        require_roles(p, {"PlatformOperator"})
        now = db.now()
        for r in db.payment_reminders.values():
            if r["status"] == "SCHEDULED" and r["due_date"] <= now:
                r["status"] = "SENT"
                models.touch(r)
                if r.get("bill_id") is not None:
                    bill = db.bills.get(r["bill_id"])
                    if bill is not None:
                        bill["reminder_status"] = "SENT"
                        models.touch(bill)
        return response.ok({})
