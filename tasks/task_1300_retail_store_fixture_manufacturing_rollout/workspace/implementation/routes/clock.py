"""Logical clock endpoint (test-driving capability)."""

from __future__ import annotations

from datetime import datetime, timezone, date

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


def _apply_clock_transitions(new_dt: datetime) -> None:
    # COMMITTED waves whose start_date has been reached -> IN_PRODUCTION
    for wave in db.waves.values():
        if wave["status"] != "COMMITTED":
            continue
        try:
            start = datetime.strptime(wave["start_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if new_dt.date() >= start:
            wave["status"] = "IN_PRODUCTION"
            db.touch(wave)

    # HELD reservations whose end_ts has been reached or passed -> EXPIRED
    for reservation in db.reservations.values():
        if reservation["status"] != "HELD":
            continue
        end_dt = reservation.get("_end_dt")
        if end_dt is None:
            continue
        if new_dt >= end_dt:
            reservation["status"] = "EXPIRED"
            db.touch(reservation)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.set_current_utc(to_iso8601)
    _apply_clock_transitions(new_dt)
    return success_object({"current_utc": db.get_current_utc()})
