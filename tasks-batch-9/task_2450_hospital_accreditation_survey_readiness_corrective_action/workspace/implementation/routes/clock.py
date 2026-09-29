"""The logical clock test-driving surface (PRD 2.4)."""

from flask import Blueprint

import cascade
from auth import require_roles
from envelope import iso, object_response
from helpers import body, req_dt
from store import db, rows, touch

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("AccreditationDirector")
    b = body()
    to = req_dt(b, "to_iso8601")

    db.clock = to

    # 1. Evidence expiry sweep — inclusive boundary.
    expired = 0
    for item in rows(db.evidence_items):
        if item["validation_state"] != "VALIDATED":
            continue
        if item["expires_at"] is None or item["expires_at"] > db.clock:
            continue
        item["validation_state"] = "EXPIRED"
        touch(item)
        expired += 1
        standard = db.standards.get(item["standard_id"])
        if standard is not None:
            cascade.on_evidence_uncounted(standard)

    # 2. Survey-window eligibility re-evaluation.
    eligible = 0
    for window in rows(db.windows):
        if window["window_state"] != "PROJECTED":
            continue
        if window["predicted_open_date"] <= db.clock <= window["predicted_close_date"]:
            window["window_state"] = "ELIGIBLE"
            touch(window)
            eligible += 1

    return object_response(
        {
            "current_utc": iso(db.clock),
            "expired_evidence_count": expired,
            "eligible_window_count": eligible,
        }
    )
