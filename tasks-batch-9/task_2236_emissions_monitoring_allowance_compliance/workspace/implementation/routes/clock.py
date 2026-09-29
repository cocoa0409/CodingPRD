"""The logical clock (PRD 2.4).

The server never reads the wall clock: every server-assigned timestamp and every
temporal comparison reads this instant, which starts at 2026-08-01T00:00:00Z.
"""

from flask import Blueprint

from constants import API_PREFIX, CALIBRATION_STALE_HOURS
from db import db, touch
from middleware import ANY_ROLE, authenticate
from response import object_response
from util import hours_before
from validation import body_dict, dt_field

bp = Blueprint("clock", __name__)


@bp.route(API_PREFIX + "/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(ANY_ROLE)
    body = body_dict()
    raw, instant = dt_field(body, "to_iso8601", required=True)

    db.current_utc = instant
    cutoff = hours_before(instant, CALIBRATION_STALE_HOURS)

    expired = []
    systems = sorted(
        db.monitoring_systems.values(), key=lambda s: (s["created_at"], s["_seq"])
    )
    for system in systems:
        if system["cal_status"] != "CAL_CURRENT":
            continue
        last = system.get("_last_calibration")
        if last is None or last >= cutoff:
            continue
        system["cal_status"] = "CAL_EXPIRED"
        touch(system)
        expired.append(system["id"])

    return object_response(
        {"current_utc": raw, "expired_monitoring_system_ids": expired}
    )
