"""Goals and habit check-ins (PRD §3.6)."""
from flask import Blueprint

from auth import authenticate, require_role, require_ownership, body, get_str, get_int, get_bool
from db import store
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_DUPLICATE_RESOURCE, not_found)
from serializers import goal as ser_goal, check_in as ser_check, base_row, append_row, touch
from timeutil import parse_date

bp = Blueprint("goals", __name__)


def _get_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise not_found("Enrollment not found")
    return e


def _get_goal(gid):
    g = store.goals.get(gid)
    if g is None:
        raise not_found("Goal not found")
    return g


def _achieved_count(goal_id):
    return sum(1 for h in store.check_ins.values()
               if h["goal_id"] == goal_id and h["completed"] is True)


@bp.post("/enrollments/<eid>/goals")
def create_goal(eid):
    role, uid = authenticate()
    require_role(role, uid, ("Client", "Coach"))
    e = _get_enrollment(eid)
    if role == "Client":
        require_ownership(e["client_id"], uid)
    else:
        require_ownership(e["coach_id"], uid)
    b = body()
    title = get_str(b, "title")
    target = get_int(b, "target_count")
    if title is None or target is None or target < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: title, target_count >= 1")
    g = base_row()
    g.update({
        "enrollment_id": e["id"],
        "title": title,
        "target_count": target,
        "goal_status": "OPEN",
    })
    store.goals[g["id"]] = g
    return success(ser_goal(g)), 201


@bp.get("/goals/<gid>")
def get_goal(gid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    return success(ser_goal(_get_goal(gid)))


@bp.post("/goals/<gid>/abandon")
def abandon_goal(gid):
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    g = _get_goal(gid)
    e = store.enrollments.get(g["enrollment_id"])
    require_ownership(e["client_id"] if e is not None else None, uid)
    if g["goal_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN goal can be abandoned")
    g["goal_status"] = "ABANDONED"
    touch(g)
    return success(ser_goal(g))


@bp.get("/enrollments/<eid>/goals")
def list_goals(eid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    _get_enrollment(eid)
    rows = [g for g in store.goals.values() if g["enrollment_id"] == eid]
    rows.sort(key=lambda g: (g["created_at"], g["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_goal(g) for g in page], meta)


@bp.post("/goals/<gid>/check-ins")
def create_check_in(gid):
    """One check-in per (goal_id, check_in_date); out-of-order dates accepted.
    Goal -> ACHIEVED the moment achieved_count reaches target_count (inclusive).
    Recomputes the owning client's engagement score (computed at read time)."""
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    g = _get_goal(gid)
    e = store.enrollments.get(g["enrollment_id"])
    require_ownership(e["client_id"] if e is not None else None, uid)
    if g["goal_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Check-ins require the goal to be OPEN")
    b = body()
    check_date = parse_date(b.get("check_in_date"))
    if check_date is not None and any(
            h["goal_id"] == gid and h["check_in_date"] == check_date
            for h in store.check_ins.values()):
        raise ApiError(ERR_DUPLICATE_RESOURCE, 409,
                       "At most one check-in per (goal_id, check_in_date)")
    completed = get_bool(b, "completed")
    if check_date is None or completed is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: check_in_date (ISO date), completed (boolean)")
    h = append_row()
    h.update({
        "goal_id": gid,
        "check_in_date": check_date,
        "completed": completed,
    })
    store.check_ins[h["id"]] = h
    # Inclusive boundary: exactly reaching target_count achieves the goal.
    if g["goal_status"] == "OPEN" and _achieved_count(gid) >= g["target_count"]:
        g["goal_status"] = "ACHIEVED"
        touch(g)
    return success(ser_check(h)), 201


@bp.get("/goals/<gid>/check-ins")
def list_check_ins(gid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    _get_goal(gid)
    rows = [h for h in store.check_ins.values() if h["goal_id"] == gid]
    rows.sort(key=lambda h: (h["created_at"], h["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_check(h) for h in page], meta)
