"""Test-driving logical clock endpoint."""

from flask import Blueprint

from db import store, parse_iso
from middleware import require_roles
from response import success_object
from validation import get_body, req_iso_datetime
from services import touch

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, _ = require_roles("PlantAdmin")
    body = get_body()
    to_dt = req_iso_datetime(body, "to_iso8601")

    store.logical_clock = to_dt

    # NO_SHOW sweep: SCHEDULED shifts whose scheduled_end has passed,
    # ordered by scheduled_end ASC, tie-break created_at ASC.
    eligible = [
        s for s in store.inspector_shifts.values()
        if s["status"] == "SCHEDULED" and store.now() > s["scheduled_end"]
    ]
    eligible.sort(key=lambda s: (s["scheduled_end"], s["created_at"]))
    for s in eligible:
        s["status"] = "NO_SHOW"
        touch(s)

    return success_object({"current_utc": store.now_iso()})
