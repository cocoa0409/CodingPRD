"""Election window endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_STALE_VERSION,
    ERR_INVALID_WINDOW_DATES,
    ERR_WINDOW_OVERLAP,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_int,
    req_date,
    opt_date,
    get_or_404,
    stamp_new,
    touch,
)
from util import fmt_date, parse_date

bp = Blueprint("election_windows", __name__)


def window_view(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "plan_id": w["plan_id"],
        "plan_year": w["plan_year"],
        "general_open_date": w["general_open_date"],
        "general_close_date": w["general_close_date"],
        "performance_period_start": w["performance_period_start"],
        "performance_period_end": w["performance_period_end"],
        "status": w["status"],
    }


@bp.post("/api/election-windows")
def create_window():
    data = body()
    from errors import ERR_INVALID_REQUEST

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    plan_year = req_int(data, "plan_year")
    open_d = req_date(data, "general_open_date")
    close_d = req_date(data, "general_close_date")
    perf_start = opt_date(data, "performance_period_start")
    perf_end = opt_date(data, "performance_period_end")
    expected = req_int(data, "expected_plan_version")
    if (perf_start is None) != (perf_end is None):
        raise_err(ERR_INVALID_REQUEST, "performance_period_start and performance_period_end are supplied together or not at all")

    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if expected != plan["version"]:
        raise_err(ERR_STALE_VERSION, "expected_plan_version does not match current Plan.version")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to create an election window")

    # Date-shape rules (temporal stage)
    if close_d.year != plan_year - 1:
        raise_err(ERR_INVALID_WINDOW_DATES, "general_close_date must fall in calendar year plan_year - 1")
    if open_d > close_d:
        raise_err(ERR_INVALID_WINDOW_DATES, "general_open_date must not fall after general_close_date")
    if perf_start is not None and (perf_end - perf_start).days < 365:
        raise_err(ERR_INVALID_WINDOW_DATES, "performance period must span at least 365 days")

    # Closed-interval overlap
    for w in db.election_windows.values():
        if w["plan_id"] != plan_id:
            continue
        a_open, a_close = open_d, close_d
        b_open, b_close = parse_date(w["general_open_date"]), parse_date(w["general_close_date"])
        if not (a_close < b_open or b_close < a_open):
            raise_err(ERR_WINDOW_OVERLAP, "Window overlaps another window of the same plan")

    window = stamp_new(
        {
            "plan_id": plan_id,
            "plan_year": plan_year,
            "general_open_date": fmt_date(open_d),
            "general_close_date": fmt_date(close_d),
            "performance_period_start": fmt_date(perf_start) if perf_start else None,
            "performance_period_end": fmt_date(perf_end) if perf_end else None,
            "status": "SCHEDULED",
        }
    )
    db.election_windows[window["id"]] = window
    touch(plan)
    return ok_object(window_view(window), 201)


@bp.get("/api/election-windows")
def list_windows():
    user_context()
    items = [w for w in db.election_windows.values()]
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [w for w in items if w["plan_id"] == plan_id]
    return _list_response([window_view(w) for w in items], request.args)


@bp.get("/api/election-windows/<windowId>")
def get_window(windowId):
    user_context()
    w = get_or_404(db.election_windows, windowId, "ElectionWindow")
    return ok_object(window_view(w))
