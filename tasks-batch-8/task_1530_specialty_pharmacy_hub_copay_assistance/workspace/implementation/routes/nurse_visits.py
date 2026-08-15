"""Nurse visits: schedule and resolve."""

from flask import Blueprint

from db import store, new_id, now_iso
from errors import (
    ApiError,
    ERR_ENROLLMENT_DISCONTINUED,
    ERR_VISIT_WINDOW_INVALID,
    ERR_VISIT_WINDOW_OVERLAP,
    ERR_ALREADY_TERMINAL,
    ERR_FORBIDDEN,
)
from middleware import require_roles, get_auth
from response import success_object, success_array
from services.common import (
    body, req_string, req_datetime, req_enum,
    get_enrollment_or_404, get_visit_or_404,
    pagination_params, paginate, touch,
)
from services.calc import serialize_visit, visits_for_enrollment

bp = Blueprint("nurse_visits", __name__)


def _fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.post("/hub/enrollments/<eid>/nurse-visits")
def create_visit(eid):
    require_roles("CaseManager")
    e = get_enrollment_or_404(eid)
    data = body()
    nurse_id = req_string(data, "nurse_id")
    window_start = req_datetime(data, "window_start")
    window_end = req_datetime(data, "window_end")

    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is terminal.", 409)
    # Domain constraint: window_end strictly after window_start.
    if window_end <= window_start:
        raise ApiError(ERR_VISIT_WINDOW_INVALID,
                       "window_end must be strictly after window_start.", 422)
    # Temporal conflict: half-open overlap with another SCHEDULED visit
    # for the same nurse_id (across all enrollments; nurse is the resource).
    for v in store.nurse_visits.values():
        if v["nurse_id"] != nurse_id or v["status"] != "SCHEDULED":
            continue
        other_start = _parse_dt(v["window_start"])
        other_end = _parse_dt(v["window_end"])
        # Half-open [start, end) overlap: start < other_end AND other_start < end.
        if window_start < other_end and other_start < window_end:
            raise ApiError(ERR_VISIT_WINDOW_OVERLAP,
                           "Visit window overlaps another scheduled visit "
                           "for this nurse.", 409)

    ts = now_iso()
    visit = {
        "id": new_id(),
        "enrollment_id": eid,
        "nurse_id": nurse_id,
        "window_start": _fmt_dt(window_start),
        "window_end": _fmt_dt(window_end),
        "status": "SCHEDULED",
        "completed_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.nurse_visits[visit["id"]] = visit
    return success_object(serialize_visit(visit), 201)


def _parse_dt(s):
    from db import _parse_iso_datetime
    return _parse_iso_datetime(s)


@bp.get("/hub/enrollments/<eid>/nurse-visits")
def list_visits(eid):
    get_auth()
    get_enrollment_or_404(eid)
    limit, offset = pagination_params()
    page, total = paginate(visits_for_enrollment(eid), limit, offset)
    return success_array([serialize_visit(v) for v in page],
                         limit, offset, total, 200)


@bp.post("/hub/nurse-visits/<vid>/resolve")
def resolve_visit(vid):
    user_id, _ = require_roles("NurseEducator")
    v = get_visit_or_404(vid)
    # Role-stage identity check: only the assigned nurse may resolve.
    if user_id != v["nurse_id"]:
        raise ApiError(ERR_FORBIDDEN,
                       "Only the assigned nurse may resolve this visit.", 403)
    data = body()
    outcome = req_enum(data, "outcome", ("COMPLETED", "NO_SHOW"))
    if v["status"] in ("COMPLETED", "NO_SHOW"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Nurse visit is terminal.", 409)

    v["status"] = outcome
    v["completed_by_user_id"] = user_id
    touch(v)
    if outcome == "COMPLETED":
        e = store.enrollments[v["enrollment_id"]]
        e["training_sessions_completed"] += 1
        touch(e)  # parent mutation bumps enrollment.version
    return success_object(serialize_visit(v), 200)
