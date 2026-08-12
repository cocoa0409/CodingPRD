"""POST /busops/_clock/set_current_utc — logical clock test-driving."""
from flask import Blueprint

import db
from envelope import success_object
from middleware import authenticate, require_roles
from services.clock import advance_clock
from validation import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.route("/busops/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    new_now = req_datetime(body, "to_iso8601")
    actor = authenticate()
    require_roles(actor, {"SystemAdmin"})
    advance_clock(new_now)
    return success_object({"current_utc": db.fmt_clock(db.clock_now())})
