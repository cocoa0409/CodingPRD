"""The administrative logical-clock endpoint (PRD §2.4).

This is the single endpoint exempt from the authentication check of §2.1.
"""

from flask import Blueprint

from auth import endpoint
from envelope import iso, object_response
from store import db
from validate import body_object, v_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(authenticated=False)
def set_current_utc():
    body = body_object()
    moment = v_datetime(body, "current_utc")
    # Setting the clock mutates no entity and triggers no sweep.
    db.set_clock(moment)
    return object_response({"current_utc": iso(moment)})
