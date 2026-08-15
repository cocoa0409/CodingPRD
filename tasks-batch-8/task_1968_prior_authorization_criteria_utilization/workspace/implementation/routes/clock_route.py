"""Admin-only logical clock driver with the TAT breach sweep."""

import clock
from db import db, touch
from middleware import ROLE_UM_ADMIN, authorize, json_body, req_dt
from response import ok
from services import EV_TAT_BREACHED, add_event
from . import make_blueprint

bp = make_blueprint("clock")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize(ROLE_UM_ADMIN)
    body = json_body()
    target = req_dt(body, "to_iso8601")
    clock.set_now(target)
    now = clock.now()

    # Idempotent breach sweep: strict comparison (now > due_at); already-flagged
    # rows are skipped and produce no duplicate events.
    requests_flagged = 0
    for req in db.requests.values():
        if (
            req["status"] in ("PENDED_REVIEW", "ESCALATED_MD")
            and not req["is_tat_breached"]
            and now > req["due_at"]
        ):
            req["is_tat_breached"] = True
            touch(req)
            add_event(
                EV_TAT_BREACHED,
                req["id"],
                req["provider_id"],
                f"TAT breached for request {req['id']} "
                f"(due_at before current clock)",
            )
            requests_flagged += 1

    appeals_flagged = 0
    for appeal in db.appeals.values():
        if (
            appeal["status"] in ("RECEIVED", "IN_REVIEW")
            and not appeal["is_tat_breached"]
            and now > appeal["due_at"]
        ):
            appeal["is_tat_breached"] = True
            touch(appeal)
            det = db.determinations.get(appeal["determination_id"])
            req = db.requests.get(det["request_id"]) if det else None
            add_event(
                EV_TAT_BREACHED,
                req["id"] if req else None,
                req["provider_id"] if req else None,
                f"TAT breached for appeal {appeal['id']} "
                f"(due_at before current clock)",
            )
            appeals_flagged += 1

    return ok(
        {
            "current_utc": clock.fmt(now),
            "requests_flagged": requests_flagged,
            "appeals_flagged": appeals_flagged,
        }
    )
