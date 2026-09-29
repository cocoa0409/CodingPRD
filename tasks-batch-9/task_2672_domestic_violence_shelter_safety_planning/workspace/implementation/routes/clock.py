"""The logical-clock endpoint and the checkpoint cascade it drives."""

from datetime import datetime, time, timedelta, timezone

from flask import Blueprint

from db import clock_iso, clock_now, db, touch
from errors import ApiError
from middleware import ROLE_AGENCY_ADMIN, auth
from response import ok
from services import cascade, derive
from validation import get_body, req_datetime

bp = Blueprint("clock", __name__)

WAITLIST_TTL_DAYS = 14


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth((ROLE_AGENCY_ADMIN,))
    body = get_body()
    target = req_datetime(body, "to_iso8601")

    if target < clock_now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")

    db.clock = target

    # waitlist expiry, driven by the new reading
    expired = 0
    shelters_touched = []
    for request in derive.rows("screening_requests"):
        if request["status"] != "WAITLISTED":
            continue
        anchor = derive.as_date(request["requested_entry_date"]) + timedelta(
            days=WAITLIST_TTL_DAYS)
        deadline = datetime.combine(anchor, time(0, 0, 0), tzinfo=timezone.utc)
        if deadline < target:
            request["status"] = "EXPIRED"
            request["waitlist_position"] = None
            touch(request)
            expired += 1
            if request["requested_shelter_id"] not in shelters_touched:
                shelters_touched.append(request["requested_shelter_id"])
    for shelter_id in shelters_touched:
        cascade.renumber_waitlist(shelter_id)

    # the wellness decay factor is clock-relative, so every staff member re-derives
    restaffed = 0
    for staff in derive.rows("staff_members"):
        if derive.recompute_staff(staff, force=False):
            restaffed += 1

    return ok({
        "current_utc": clock_iso(),
        "expired_screening_request_count": expired,
        "restaffed_posture_count": restaffed,
    })
