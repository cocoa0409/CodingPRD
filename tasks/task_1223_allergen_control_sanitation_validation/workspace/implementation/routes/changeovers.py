from flask import Blueprint, request

from db import db, new_entity, public, touch
from errors import ApiError
from logic import get_or_404, recompute_posture
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from util import body, opt_str, req_int, req_str

bp = Blueprint("changeovers", __name__)


@bp.post("/qa/changeovers")
@require_roles("QaSupervisor")
def create_changeover():
    b = body()
    line = get_or_404("lines", req_str(b, "line_id"))
    from_run_id = opt_str(b, "from_run_id")
    from_run = None
    if from_run_id is not None:
        from_run = get_or_404("runs", from_run_id)
    to_run = get_or_404("runs", req_str(b, "to_run_id"))
    procedure = get_or_404("procedures", req_str(b, "procedure_id"))
    scheduled_minutes = req_int(b, "scheduled_minutes")
    if scheduled_minutes < to_run["scheduled_changeover_minutes"]:
        raise ApiError("ERR_CHANGEOVER_BUDGET_SHORT", 422,
                       "scheduled_minutes is below the to-run's scheduled_changeover_minutes")
    ent = new_entity({
        "line_id": line["id"],
        "from_run_id": from_run["id"] if from_run is not None else None,
        "to_run_id": to_run["id"],
        "procedure_id": procedure["id"],
        "scheduled_minutes": scheduled_minutes,
        "actual_minutes": None,
        "validation_score": None,
        "status": "PLANNED",
    })
    db["changeovers"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/changeovers")
@require_roles(*ALL_ROLES)
def list_changeovers():
    items = list(db["changeovers"].values())
    for param in ("line_id", "to_run_id", "from_run_id", "procedure_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    return ok_list(items)


@bp.get("/qa/changeovers/<changeoverId>")
@require_roles(*ALL_ROLES)
def get_changeover(changeoverId):
    return ok(public(get_or_404("changeovers", changeoverId)))


@bp.post("/qa/changeovers/<changeoverId>/begin")
@require_roles("LineOperator")
def begin_changeover(changeoverId):
    c = get_or_404("changeovers", changeoverId)
    if c["status"] != "PLANNED":
        raise ApiError("ERR_CHANGEOVER_NOT_PLANNED", 409,
                       "Changeover is not in PLANNED")
    to_run = get_or_404("runs", c["to_run_id"])
    if to_run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_NOT_SCHEDULED", 409,
                       "to_run is not in SCHEDULED")
    line = get_or_404("lines", c["line_id"])
    if line["posture"] not in ("OPEN", "RESTRICTED"):
        raise ApiError("ERR_LINE_ON_HOLD", 409,
                       "Line posture HOLD blocks changeover begin")
    c["status"] = "IN_EXECUTION"
    touch(c)
    touch(line)
    return ok(public(c))


@bp.post("/qa/changeovers/<changeoverId>/finish-execution")
@require_roles("LineOperator")
def finish_execution(changeoverId):
    c = get_or_404("changeovers", changeoverId)
    if c["status"] != "IN_EXECUTION":
        raise ApiError("ERR_CHANGEOVER_NOT_IN_EXECUTION", 409,
                       "Changeover is not in IN_EXECUTION")
    b = body()
    actual = req_int(b, "actual_minutes", minv=0)
    c["actual_minutes"] = actual
    c["status"] = "SWAB_PENDING"
    touch(c)
    return ok(public(c))


@bp.post("/qa/changeovers/<changeoverId>/reswab")
@require_roles("LineOperator")
def reswab_changeover(changeoverId):
    c = get_or_404("changeovers", changeoverId)
    if c["status"] != "REWORK_REQUIRED":
        raise ApiError("ERR_CHANGEOVER_NOT_REWORK", 409,
                       "Changeover is not in REWORK_REQUIRED")
    for s in db["swabs"].values():
        if s["changeover_id"] == c["id"] and s["outcome"] == "FAIL":
            s["outcome"] = "INVALIDATED"
            s["invalidated_reason"] = "RESWAB"
            touch(s)
    c["status"] = "SWAB_PENDING"
    touch(c)
    line = db["lines"].get(c["line_id"])
    if line is not None:
        recompute_posture(line)
    return ok(public(c))


@bp.post("/qa/changeovers/<changeoverId>/cancel")
@require_roles("QaSupervisor")
def cancel_changeover(changeoverId):
    c = get_or_404("changeovers", changeoverId)
    if c["status"] not in ("PLANNED", "IN_EXECUTION"):
        raise ApiError("ERR_CHANGEOVER_TERMINAL", 409,
                       "Changeover is terminal for cancel")
    if c["status"] == "IN_EXECUTION":
        for s in db["swabs"].values():
            if s["changeover_id"] == c["id"] and s["outcome"] != "INVALIDATED":
                s["outcome"] = "INVALIDATED"
                s["invalidated_reason"] = "CHANGEOVER_CANCELLED"
                touch(s)
    c["status"] = "CANCELLED"
    touch(c)
    return ok(public(c))
