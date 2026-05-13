"""Exercise window routes."""

from flask import Blueprint, request
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_INVALID_TIME_INTERVAL,
    ERR_BLACKOUT_OVERLAPS_WINDOW, ERR_WINDOW_NOT_CLOSED,
    ERR_OPEN_EXERCISES_EXIST, ERR_CROSS_RESOURCE_MISMATCH,
)
from services.common import (
    init_common, bump_version, check_occ, get_body, get_or_404,
    get_pagination, paginate_list, sort_by_created_at_asc,
    require_string, require_iso_datetime,
)
from services.time_util import format_iso, parse_iso
from services.serializers import serialize_window
from services.audit import append_audit


bp = Blueprint("windows", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [a_start, a_end) vs [b_start, b_end)."""
    return not (a_end <= b_start or b_end <= a_start)


def _plan_blackouts(plan_id):
    out = []
    for ev in DB["corporate_events"].values():
        if ev["plan_id"] != plan_id:
            continue
        if ev["event_type"] in ("EARNINGS_BLACKOUT", "MATERIAL_EVENT_BLACKOUT"):
            out.append(ev)
    return out


@bp.post("/option-plans/<plan_id>/exercise-windows")
@auth_required(["PlanAdministrator"])
def create_window(plan_id):
    plan = get_or_404("option_plans", plan_id)
    body = get_body()
    label = require_string(body, "label")
    open_dt = require_iso_datetime(body, "open_ts")
    close_dt = require_iso_datetime(body, "close_ts")
    if open_dt >= close_dt:
        raise_error(ERR_INVALID_TIME_INTERVAL, "open_ts must be < close_ts")
    # Overlap with any blackout
    for ev in _plan_blackouts(plan_id):
        b_start = parse_iso(ev["effective_ts"])
        b_end = parse_iso(ev["blackout_end_ts"])
        if _intervals_overlap(open_dt, close_dt, b_start, b_end):
            raise_error(ERR_BLACKOUT_OVERLAPS_WINDOW, "Window overlaps blackout")
    # Unique label within plan
    for w in DB["exercise_windows"].values():
        if w["plan_id"] == plan_id and w["label"] == label:
            raise_error(ERR_INVALID_REQUEST, "label must be unique within plan")
    wid = new_id()
    win = {
        "id": wid,
        "plan_id": plan_id,
        "label": label,
        "open_ts": format_iso(open_dt),
        "close_ts": format_iso(close_dt),
        "status": "SCHEDULED",
        "notified_at": None,
    }
    init_common(win)
    DB["exercise_windows"][wid] = win
    return success_response(serialize_window(win), http_status=201)


@bp.get("/option-plans/<plan_id>/exercise-windows")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "Grantee", "AuditViewer"])
def list_windows(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = [w for w in DB["exercise_windows"].values() if w["plan_id"] == plan_id]
    if status:
        items = [w for w in items if w["status"] == status]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_window(w) for w in sliced], total, limit, offset)


@bp.post("/option-plans/<plan_id>/exercise-windows/sweep")
@auth_required(["PlanAdministrator"])
def sweep_windows(plan_id):
    plan = get_or_404("option_plans", plan_id)
    clock = parse_iso(plan["current_clock_ts"]) if plan.get("current_clock_ts") else None
    out = []
    if clock is None:
        items = [w for w in DB["exercise_windows"].values() if w["plan_id"] == plan_id]
        items = sort_by_created_at_asc(items)
        return list_response([serialize_window(w) for w in items], len(items), 100, 0)

    blackouts = _plan_blackouts(plan_id)
    for w in list(DB["exercise_windows"].values()):
        if w["plan_id"] != plan_id:
            continue
        if w["status"] == "SCHEDULED":
            open_ts = parse_iso(w["open_ts"])
            close_ts = parse_iso(w["close_ts"])
            # If plan is CLOSED then transition any SCHEDULED to CLOSED
            if plan["status"] == "CLOSED":
                w["status"] = "CLOSED"
                bump_version(w)
                continue
            if clock < open_ts:
                continue
            if clock >= close_ts:
                # Already past the window; mark CLOSED
                w["status"] = "CLOSED"
                bump_version(w)
                _reject_submitted_apps_for_window(w, plan)
                continue
            # Open candidate; check blackout overlap
            overlapping = False
            for ev in blackouts:
                bs = parse_iso(ev["effective_ts"])
                be = parse_iso(ev["blackout_end_ts"])
                if _intervals_overlap(open_ts, close_ts, bs, be):
                    overlapping = True
                    break
            if overlapping:
                continue
            w["status"] = "OPEN"
            w["notified_at"] = format_iso(clock)
            bump_version(w)
            _notify_grantees_audit(plan, w)
        elif w["status"] == "OPEN":
            close_ts = parse_iso(w["close_ts"])
            if plan["status"] == "CLOSED" or clock >= close_ts:
                w["status"] = "CLOSED"
                bump_version(w)
                _reject_submitted_apps_for_window(w, plan)
        out.append(w)
    items = [w for w in DB["exercise_windows"].values() if w["plan_id"] == plan_id]
    items = sort_by_created_at_asc(items)
    return list_response([serialize_window(w) for w in items], len(items), 100, 0)


def _notify_grantees_audit(plan, window):
    for g in DB["grantees"].values():
        if g["plan_id"] != plan["id"]:
            continue
        if g["eligibility_status"] != "ELIGIBLE":
            continue
        append_audit(plan, "EXERCISE_SUBMITTED", "ExerciseWindow", window["id"],
                     {"event": "GRANTEE_NOTIFIED", "grantee_id": g["id"], "window_id": window["id"]})


def _reject_submitted_apps_for_window(window, plan):
    for app in DB["exercise_applications"].values():
        if app["window_id"] != window["id"]:
            continue
        if app["status"] == "SUBMITTED":
            app["status"] = "REJECTED"
            app["_rejection_note"] = "WINDOW_CLOSED"
            bump_version(app)
            append_audit(plan, "EXERCISE_REJECTED", "ExerciseApplication", app["id"],
                         {"reason": "WINDOW_CLOSED"})


@bp.post("/option-plans/<plan_id>/exercise-windows/<window_id>/archive")
@auth_required(["PlanAdministrator"])
def archive_window(plan_id, window_id):
    get_or_404("option_plans", plan_id)
    w = get_or_404("exercise_windows", window_id)
    if w["plan_id"] != plan_id:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Window does not belong to plan")
    body = get_body()
    check_occ(w, body)
    if w["status"] != "CLOSED":
        raise_error(ERR_WINDOW_NOT_CLOSED, "Window not in CLOSED")
    # No non-terminal applications
    non_terminal = {"SUBMITTED", "ELIGIBILITY_VERIFIED", "PAYMENT_RECEIVED", "TAX_WITHHELD"}
    for app in DB["exercise_applications"].values():
        if app["window_id"] == window_id and app["status"] in non_terminal:
            raise_error(ERR_OPEN_EXERCISES_EXIST, "Window has non-terminal applications")
    w["status"] = "ARCHIVED"
    bump_version(w)
    return success_response(serialize_window(w))
