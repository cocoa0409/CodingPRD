"""Logical-clock test-driving endpoints (PRD 2.9):
POST /_clock/set_current_utc and POST /_clock/tick."""
from datetime import timedelta

from flask import Blueprint

import db
import services
from envelope import success
from helpers import body, bad, parse_instant
from middleware import require_roles

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("UtilityAdmin")
    b = body()
    raw = b.get("to_iso8601")
    if raw is None:
        bad("to_iso8601 is required")
    dt = parse_instant(raw, "to_iso8601")
    db.set_clock(dt)
    return success({"current_utc": db.fmt_dt(db.now())})


@bp.post("/_clock/tick")
def tick():
    require_roles("UtilityAdmin")
    now = db.now()
    counts = {
        "wet_well_cleanings_marked_overdue": 0,
        "generator_tests_marked_overdue": 0,
        "stations_recomputed": 0,
    }
    # SCHEDULED cleanings more than 24h past their planned start -> OVERDUE,
    # each firing a MINOR CLEANING_OVERDUE alarm.
    for c in list(db.wet_well_cleanings.values()):
        if c["status"] == "SCHEDULED" and now > c["scheduled_for"] + timedelta(hours=24):
            c["status"] = "OVERDUE"
            db.touch(c)
            services.auto_alarm(c["station_id"], "MINOR", "CLEANING_OVERDUE")
            counts["wet_well_cleanings_marked_overdue"] += 1
    # SCHEDULED generator tests more than 24h past their planned start -> OVERDUE.
    for t in list(db.generator_tests.values()):
        if t["status"] == "SCHEDULED" and now > t["scheduled_for"] + timedelta(hours=24):
            t["status"] = "OVERDUE"
            db.touch(t)
            counts["generator_tests_marked_overdue"] += 1
    # Station postures recomputed against the new "now".
    for st in list(db.stations.values()):
        if services.sync_station(st):
            counts["stations_recomputed"] += 1
    return success({"transitioned_counts": counts})
