"""Logical clock endpoint (PRD §2.4, scaffold §1.5)."""
from flask import Blueprint

from db import db
from middleware import authenticate
from response import success
from services.common import get_body, parse_iso
from errors import err, ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)

ALL_ROLES = {"RevenueManager", "GroupSalesManager", "ChannelManager", "Analyst"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # All four roles may set the clock.
    authenticate()
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    dt = parse_iso(body["to_iso8601"], "to_iso8601")
    db.clock = dt
    return success({}, status=200)
