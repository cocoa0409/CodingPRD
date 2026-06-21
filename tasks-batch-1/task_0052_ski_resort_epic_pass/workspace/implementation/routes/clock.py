from datetime import datetime, timezone

from flask import Blueprint, request

import errors
from db import db, SEASON_END_DATE
from middleware import authenticate, require_roles
from response import success
from services import validate as V
from services.common import touch
from services.cascade import cancel_reserved_buddy_tickets, recompute_buddy_remaining

bp = Blueprint("clock", __name__)


def _parse_iso(value):
    if not isinstance(value, str) or not value:
        raise errors.validation("to_iso8601 is required and must be an ISO 8601 string")
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.validation("to_iso8601 must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_roles(role, {"NetworkAdmin"})
    body = V.get_body(request)
    to_iso = body.get("to_iso8601")
    dt = _parse_iso(to_iso)
    db.clock = dt

    new_date = dt.strftime("%Y-%m-%d")
    # Season-end auto-expiry: only when the new clock date is strictly later
    # than SEASON_END_DATE (PRD §3.6).
    if new_date > SEASON_END_DATE:
        for pass_rec in db.passes.values():
            if pass_rec["status"] == "ACTIVE":
                cancel_reserved_buddy_tickets(pass_rec["id"])
                recompute_buddy_remaining(pass_rec)
                pass_rec["status"] = "EXPIRED"
                touch(pass_rec)

    return success({})
