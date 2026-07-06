"""GroupProject + nested shift-listing routes."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                    ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE)
from response import envelope_object, envelope_array
from services import validators, pagination, projects
from services.serializers import group_project_dto, project_shift_dto
from db import parse_iso

bp = Blueprint("group_projects", __name__)


@bp.route("/group-projects", methods=["POST"])
def create_project():
    user_id, _ = require_role({ROLE_ORGANIZER})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, [
        "organizer_member_id", "title", "window_start_utc", "window_end_utc"
    ])
    organizer_id = validators.require_str(payload, "organizer_member_id")
    title = validators.require_str(payload, "title")
    ws = validators.require_datetime(payload, "window_start_utc")
    we = validators.require_datetime(payload, "window_end_utc")
    if parse_iso(we) <= parse_iso(ws):
        raise_err(ERR_INVALID_REQUEST, "window_end_utc must be > window_start_utc")
    ratio = validators.require_ratio_two_dp(payload, "minimum_completed_ratio", default=0.60)

    if db.members.get(organizer_id) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "organizer member not found")
    if organizer_id != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal project.organizer_member_id")

    p = {
        "organizer_member_id": organizer_id,
        "title": title,
        "window_start_utc": ws,
        "window_end_utc": we,
        "minimum_completed_ratio": ratio,
        "aggregate_state": "PLANNING",
        "total_committed_minutes": 0,
        "_published": False,
        "_cancelled": False,
    }
    db.stamp_new(p)
    db.group_projects[p["id"]] = p
    return envelope_object(group_project_dto(p), status=201)


@bp.route("/group-projects", methods=["GET"])
def list_projects():
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.group_projects.values())
    for p in items:
        projects.recompute_aggregate_state(p)
    for k in ("organizer_member_id", "aggregate_state"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([group_project_dto(x) for x in window], limit, offset, total)


@bp.route("/group-projects/<pid>", methods=["GET"])
def get_project(pid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    p = db.group_projects.get(pid)
    if p is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Project not found")
    projects.recompute_total_committed_minutes(pid)
    projects.recompute_aggregate_state(p)
    return envelope_object(group_project_dto(p), status=200)


@bp.route("/group-projects/<pid>/publish", methods=["POST"])
def publish_project(pid):
    user_id, _ = require_role({ROLE_ORGANIZER})
    p = db.group_projects.get(pid)
    if p is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Project not found")
    if p["organizer_member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be project.organizer_member_id")
    if p["_cancelled"] or p["_published"]:
        raise_err(ERR_INVALID_STATE, "Project must be in PLANNING")
    shifts = [s for s in db.project_shifts.values() if s["project_id"] == pid]
    if not shifts:
        raise_err(ERR_INVALID_STATE, "at least one ProjectShift is required to publish")
    if db.clock_dt() > parse_iso(p["window_start_utc"]):
        raise_err(ERR_INVALID_STATE, "logical clock has already passed window_start_utc")
    p["_published"] = True
    projects.recompute_aggregate_state(p)
    db.touch(p)
    return envelope_object(group_project_dto(p), status=200)


@bp.route("/group-projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    user_id, _ = require_role({ROLE_ORGANIZER})
    p = db.group_projects.get(pid)
    if p is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Project not found")
    if p["organizer_member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be project.organizer_member_id")

    if p["_cancelled"] or p["aggregate_state"] in ("COMPLETED", "CANCELLED"):
        raise_err(ERR_INVALID_STATE, "project already terminal")

    projects.recompute_aggregate_state(p)
    state = p["aggregate_state"]
    if state == "PLANNING":
        pass  # unconditional beyond ownership
    elif state == "OPEN":
        shifts = [s for s in db.project_shifts.values() if s["project_id"] == pid]
        if shifts:
            earliest = min(parse_iso(s["shift_start_utc"]).timestamp() for s in shifts)
            if db.clock_dt().timestamp() >= earliest:
                raise_err(ERR_INVALID_STATE, "cannot cancel OPEN project after earliest shift start")
    else:
        raise_err(ERR_INVALID_STATE, f"cannot cancel from aggregate_state={state}")

    # Cascade
    p["_cancelled"] = True
    p["aggregate_state"] = "CANCELLED"
    db.touch(p)
    for s in db.project_shifts.values():
        if s["project_id"] == pid and s["status"] in ("OPEN", "FILLED"):
            was_filled = s["status"] == "FILLED"
            s["status"] = "CANCELLED"
            db.touch(s)
            if was_filled:
                # cascade CONFIRMED assignments to CANCELLED
                for a in db.shift_assignments.values():
                    if a["shift_id"] == s["id"] and a["status"] == "CONFIRMED":
                        a["status"] = "CANCELLED"
                        db.touch(a)
            else:
                # OPEN shift cascade: also cancel any CONFIRMED assignments (defensive)
                for a in db.shift_assignments.values():
                    if a["shift_id"] == s["id"] and a["status"] == "CONFIRMED":
                        a["status"] = "CANCELLED"
                        db.touch(a)
    projects.recompute_total_committed_minutes(pid)
    return envelope_object(group_project_dto(p), status=200)


@bp.route("/group-projects/<pid>/shifts", methods=["POST"])
def create_shift(pid):
    user_id, _ = require_role({ROLE_ORGANIZER})
    p = db.group_projects.get(pid)
    if p is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Project not found")
    if p["organizer_member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be project.organizer_member_id")

    projects.recompute_aggregate_state(p)
    if p["aggregate_state"] not in ("PLANNING", "OPEN"):
        raise_err(ERR_INVALID_STATE, "shifts may only be added while project is PLANNING or OPEN")

    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["role_label", "shift_start_utc", "duration_minutes", "capacity"])
    role_label = validators.require_str(payload, "role_label")
    ss = validators.require_datetime(payload, "shift_start_utc")
    dur = validators.require_minute_multiple(payload, "duration_minutes", 15, 480)
    cap = validators.require_positive_int(payload, "capacity")

    # shift_start must lie in [window_start, window_end]
    ss_dt = parse_iso(ss)
    if not (parse_iso(p["window_start_utc"]) <= ss_dt <= parse_iso(p["window_end_utc"])):
        raise_err(ERR_INVALID_REQUEST, "shift_start_utc must lie within project window")

    s = {
        "project_id": pid,
        "role_label": role_label,
        "shift_start_utc": ss,
        "duration_minutes": dur,
        "capacity": cap,
        "status": "OPEN",
    }
    db.stamp_new(s)
    db.project_shifts[s["id"]] = s
    return envelope_object(project_shift_dto(s), status=201)


@bp.route("/group-projects/<pid>/shifts", methods=["GET"])
def list_shifts(pid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    if db.group_projects.get(pid) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Project not found")
    limit, offset = pagination.parse_pagination()
    items = [s for s in db.project_shifts.values() if s["project_id"] == pid]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([project_shift_dto(s) for s in window], limit, offset, total)
