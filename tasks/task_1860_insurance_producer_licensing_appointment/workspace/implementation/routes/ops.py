"""The logical clock test-driving surface (PRD 2.5)."""

from flask import Blueprint

from core import cascade
from core.clock import render_instant
from core.envelope import object_response
from core.pipeline import authorize, req_dt
from core.store import db

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    ctx = authorize("CarrierAdmin")
    to = req_dt(ctx.body, "to_iso8601")
    db.now = to
    # Advancing the clock runs the scheduled compliance sweep.
    cascade.sweep()
    return object_response({"current_utc": render_instant(db.now)}, 200)
