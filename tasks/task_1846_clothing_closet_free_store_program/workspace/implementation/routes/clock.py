"""Logical clock administration (PRD 2.4)."""
from flask import Blueprint

import db
import services as svc
from middleware import require_roles
from response import ok
from util import fmt_dt, get_body, v_dt

bp = Blueprint("clock", __name__)


@bp.post("/closet/_clock/set_current_utc")
@require_roles("ProgramAdmin")
def set_clock():
    data = get_body()
    to = v_dt(data, "to_iso8601")
    db.set_clock(to)
    return ok({"current_utc": fmt_dt(db.now())}, 200)
