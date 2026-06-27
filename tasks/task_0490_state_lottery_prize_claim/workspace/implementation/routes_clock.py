"""Logical clock control + escheat sweep (PRD 2.4, 3.10)."""
from flask import Blueprint, request

from clock import clock
from db import db
from middleware import get_auth, require_roles
from models import _stamp_create, touch
from response import success
from util import parse_iso8601
from validate import require_body

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "LicensingAdmin"})
    body = require_body(request.get_json(silent=True))
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        from errors import err
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    target = parse_iso8601(to_iso, "to_iso8601")
    clock.set(target)
    return success({}, 200)


@clock_bp.route("/_clock/run_escheat_sweep", methods=["POST"])
def run_escheat_sweep():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})

    swept_ids = []
    now = clock.now
    # Snapshot ticket list to avoid mutating during iteration concerns.
    for ticket in list(db.tickets.values()):
        if (ticket["validation_status"] == "VALIDATED_WINNER"
                and ticket["claim_deadline"] is not None
                and ticket["claim_deadline"] < now):
            ticket["validation_status"] = "ESCHEATED"
            touch(ticket)
            record = {
                "ticket_id": ticket["id"],
                "escheated_amount_cents": ticket["gross_prize_cents"],
                "escheated_at": now,
            }
            _stamp_create(record)
            db.escheat_records[record["id"]] = record
            swept_ids.append(ticket["id"])

    return success({
        "escheated_count": len(swept_ids),
        "escheated_ticket_ids": swept_ids,
    }, 200)
