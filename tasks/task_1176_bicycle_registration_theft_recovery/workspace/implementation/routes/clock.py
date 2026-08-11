"""POST /registry/_clock/set_current_utc — logical clock (PRD §2.4)."""
from flask import Blueprint

import db
from middleware import body, require_roles
from response import ok_object
from routes.common import field
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/registry/_clock/set_current_utc")
@require_roles("Admin")
def set_current_utc():
    to_iso8601 = field(body(), "to_iso8601", "datetime", required=True)
    db.set_clock(to_iso8601)
    return ok_object({"current_utc": fmt_dt(db.now())})
