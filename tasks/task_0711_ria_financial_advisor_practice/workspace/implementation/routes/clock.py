"""Logical clock control (PRD §2.4)."""

from flask import Blueprint

from db import db, _iso_ms
from middleware import authenticate, authorize
from response import ok
from util import body, require, parse_iso_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    authorize(role, {"BillingAdmin", "ComplianceOfficer", "Advisor"})
    data = body()
    raw = require(data, "to_iso8601")
    dt = parse_iso_datetime(raw, "to_iso8601")
    db.set_clock(dt)
    return ok({"current_utc": _iso_ms(dt)})
