"""Test-driving endpoints: deterministic clock and portal-expiration sweep."""

from flask import Blueprint

import db
from errors import invalid_request
from helpers import get_body, require_field
from middleware import require_roles
from response import ok_object

bp = Blueprint("system_ops", __name__)


@bp.post("/ncaa/_clock/set_current_utc")
def set_clock():
    require_roles("ComplianceOfficer")
    body = get_body()
    to_iso = require_field(body, "to_iso8601", str)
    # Validate by parsing; rebuild a canonical .000Z-style string for consistency.
    try:
        dt = db.parse_iso(to_iso)
    except ValueError as e:
        raise invalid_request(str(e))
    canonical = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    db.set_clock(canonical)
    return ok_object({"current_utc": canonical})


@bp.post("/ncaa/_jobs/sweep-portal-expirations")
def sweep_portal_expirations():
    require_roles("ComplianceOfficer")
    now_dt = db.current_utc_dt()
    # Iterate entries deterministically by created_at ASC for cascade ordering.
    entries = list(db.transfer_portal_entries.values())
    entries.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    expired_ids = []
    for entry in entries:
        if entry["status"] != "ENTERED":
            continue
        if now_dt >= db.parse_iso(entry["window_closes_at"]):
            entry["status"] = "EXPIRED"
            db.stamp_update(entry)
            athlete = db.student_athletes.get(entry["student_athlete_id"])
            if athlete is not None and athlete.get("in_transfer_portal"):
                athlete["in_transfer_portal"] = False
                db.stamp_update(athlete)
            expired_ids.append(entry["id"])
    return ok_object({
        "expired_count": len(expired_ids),
        "expired_entry_ids": expired_ids,
    })
