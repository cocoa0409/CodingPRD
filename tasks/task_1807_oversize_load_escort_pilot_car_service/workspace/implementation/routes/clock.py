"""Logical clock endpoint (Dispatcher-only)."""

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object
from services import cascade
from util import body_json, req_dt, fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("Dispatcher")
    data = body_json(request)
    to = req_dt(data, "to_iso8601")
    db.set_clock(to)
    cascade.sweep_permit_expiry()
    return success_object({"current_utc": fmt_dt(db.now())})
