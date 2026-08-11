"""Logical clock endpoint."""
from flask import Blueprint
import db
from db import clock, format_ts, parse_ts
from errors import err
from middleware import require_role, get_body, require_fields
from response import success_obj

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        new_dt = parse_ts(body["to_iso8601"])
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid ISO8601 timestamp")
    clock.set(new_dt)
    # Sweep PENDING NOTIFICATION permit cases past deadline -> EXPIRED
    from services.common import touch
    for p in list(db.permit_cases.values()):
        if p["kind"] == "NOTIFICATION" and p["status"] == "PENDING" and p.get("deadline_at"):
            deadline = parse_ts(p["deadline_at"])
            if new_dt > deadline:
                p["status"] = "EXPIRED"
                touch(p)
                job = db.jobs.get(p["job_id"])
                if job is not None:
                    job["compliance_breach"] = True
                    touch(job)
    return success_obj({"current_utc": format_ts(clock.now())})
