"""Logical clock endpoint."""

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services.core import lazy_all, now_stamp_helper
from util import get_body, require, parse_instant, reject_unknown

bp = Blueprint("clock", __name__)


@bp.post("/agronomy/_clock/set_current_utc")
def set_clock():
    require_roles("BranchAdmin")
    body = get_body()
    reject_unknown(body, {"to_iso8601"})
    instant = parse_instant(require(body, "to_iso8601"), "to_iso8601")
    db.CLOCK.set(instant)
    lazy_all()
    return success_object({"current_utc": now_stamp_helper()})
