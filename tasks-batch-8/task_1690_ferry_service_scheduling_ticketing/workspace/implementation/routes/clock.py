"""Logical clock endpoint (PRD §2.4)."""

from flask import Blueprint, request

from db import db, _parse_iso, iso_out
from middleware import require_roles
from response import success_object
from services.fare_schedule import evaluate_fare_transitions

bp = Blueprint("clock", __name__)


@bp.post("/ferry/_clock/set_current_utc")
def set_clock():
    require_roles("SchedulerAdmin")
    payload = request.get_json(silent=True) or {}
    db.current_utc = _parse_iso(payload.get("to_iso8601"))
    # Advance-based auto transitions (§2.4)
    evaluate_fare_transitions()
    return success_object({"current_utc": iso_out(db.current_utc)})
