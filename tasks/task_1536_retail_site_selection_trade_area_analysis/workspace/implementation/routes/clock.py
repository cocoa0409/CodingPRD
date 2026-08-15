"""Logical clock (PRD §2.8): advance and fire deadline sweeps."""

from flask import Blueprint

from db import db
from middleware import require_roles
from response import ok_object
from services import touch
from util import get_body, req_datetime

bp = Blueprint("clock", __name__)


def _fmt_clock(dt):
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_body(required=True)
    _raw, dt = req_datetime(body, "to_iso8601")
    db.clock = dt
    # Fire every time-based transition whose deadline is strictly before the
    # new time. DECIDED reviews are never swept by the clock.
    today = dt.date()
    for loi in db.lois.values():
        if (loi["loi_status"] in ("SENT", "COUNTERED")
                and loi["_end_d"] < today):
            loi["loi_status"] = "EXPIRED"
            touch(loi)
    for review in db.reviews.values():
        if (review["review_status"] == "OPEN"
                and review["expires_dt"] < dt):
            review["review_status"] = "EXPIRED"
            touch(review)
            site = db.sites[review["site_id"]]
            if site["site_status"] == "IN_COMMITTEE":
                site["site_status"] = "REJECTED"
                touch(site)
    return ok_object({"current_utc": _fmt_clock(db.clock)})
