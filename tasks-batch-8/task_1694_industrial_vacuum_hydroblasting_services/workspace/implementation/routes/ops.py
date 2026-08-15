"""Operations endpoints: per-site daily close and the logical clock (PRD 2.5)."""

from datetime import timedelta

from flask import Blueprint

from db import store
from errors import bad_request, not_found
from middleware import require_roles
from response import success_object
from util import fmt_clock, get_body, now, parse_datetime, touch

bp = Blueprint("ops", __name__)


@bp.post("/v1/sites/<siteId>/daily-close")
def daily_close(siteId):
    require_roles(["ProjectManager"])
    site = store.sites.get(siteId)
    if site is None:
        raise not_found("Site not found")
    current = now()
    job_ids = {j["id"] for j in store.jobs.values() if j["site_id"] == siteId}

    expired_permit_ids = []
    for permit in store.permits.values():
        if (permit["job_id"] in job_ids
                and permit["status"] in ("ISSUED", "ACTIVE", "SUSPENDED")
                and permit["valid_until"] < current):
            permit["status"] = "EXPIRED"
            touch(permit)
            expired_permit_ids.append(permit["id"])

    cancelled_assignment_ids = []
    cutoff = current - timedelta(hours=24)
    for assignment in store.assignments.values():
        if (assignment["job_id"] in job_ids
                and assignment["status"] == "SCHEDULED"
                and assignment["window_start"] < cutoff):
            assignment["status"] = "CANCELLED"
            touch(assignment)
            cancelled_assignment_ids.append(assignment["id"])

    return success_object({
        "expired_permit_ids": expired_permit_ids,
        "cancelled_assignment_ids": cancelled_assignment_ids,
    })


@bp.post("/v1/_clock/set_current_utc")
def set_current_utc():
    require_roles(["PlatformAdmin"])
    body = get_body()
    target = parse_datetime(body.get("to_iso8601"))
    if target is None:
        raise bad_request("to_iso8601 must be an ISO 8601 datetime")
    # Advancing the clock mutates no entities; sweeps run only via daily-close.
    store.clock = target
    return success_object({"current_utc": fmt_clock(store.clock)})
