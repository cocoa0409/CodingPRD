"""RegressionRun endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from config import (
    DEFECT_FIXED, DEFECT_VERIFIED,
    ROLE_RELEASE_MANAGER, ROLE_ANY,
    RR_QUEUED, RR_RUNNING, RR_PASSED, RR_FAILED,
    REGRESSION_COOLDOWN_MINUTES,
)
from errors import (
    AppError, ERR_DEFECT_NOT_FIXED, ERR_INVALID_REQUEST,
    ERR_REGRESSION_COOLDOWN_ACTIVE, ERR_REGRESSION_INVALID_SCOPE,
    ERR_REGRESSION_NOT_QUEUED, ERR_REGRESSION_NOT_RUNNING,
)
from middleware import require_role
from response import parse_pagination, success, success_list
from services.audit import append_audit
from services.defect_logic import reopen_cascade
from services.serializers import regression_run_dto
from services.validators import (
    check_version, find_defect_or_404, find_project_or_404, find_regression_or_404,
    ensure_project_active, get_json, require_enum, require_str,
)

bp = Blueprint("regression_runs", __name__)


@bp.post("/defects/<defect_id>/regression-runs")
def queue_regression_run(defect_id):
    require_role(ROLE_RELEASE_MANAGER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if d["status"] not in (DEFECT_FIXED, DEFECT_VERIFIED):
        raise AppError(ERR_DEFECT_NOT_FIXED,
                       f"Defect must be FIXED or VERIFIED; was {d['status']}", 409)

    test_suite_key = require_str(body, "test_suite_key")
    impact_scope = body.get("impact_scope")
    if not isinstance(impact_scope, list):
        raise AppError(ERR_INVALID_REQUEST, "impact_scope must be array", 400)
    if d["module_id"] not in impact_scope:
        raise AppError(ERR_REGRESSION_INVALID_SCOPE,
                       "impact_scope must include defect.module_id", 400)

    row = db.insert("regression_runs", {
        "defect_id": defect_id,
        "module_id": d["module_id"],
        "test_suite_key": test_suite_key,
        "started_at_minute": project["clock_minute"],
        "ended_at_minute": None,
        "result": None,
        "impact_scope": list(impact_scope),
        "status": RR_QUEUED,
    })
    return success(regression_run_dto(row), 201)


@bp.post("/regression-runs/<rr_id>/start")
def start_regression(rr_id):
    require_role(ROLE_RELEASE_MANAGER)
    body = get_json()
    rr = find_regression_or_404(rr_id)
    d = find_defect_or_404(rr["defect_id"])
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if rr["status"] != RR_QUEUED:
        raise AppError(ERR_REGRESSION_NOT_QUEUED,
                       f"RegressionRun must be QUEUED; was {rr['status']}", 409)
    if d["status"] not in (DEFECT_FIXED, DEFECT_VERIFIED):
        raise AppError(ERR_DEFECT_NOT_FIXED,
                       f"Defect must be FIXED or VERIFIED; was {d['status']}", 409)

    # Cooldown
    prior_runs = [r for r in db.all_rows("regression_runs")
                  if r["module_id"] == rr["module_id"]
                  and r["status"] in (RR_RUNNING, RR_PASSED, RR_FAILED)
                  and r["id"] != rr["id"]]
    if prior_runs:
        max_start = max(r["started_at_minute"] for r in prior_runs)
        delta = project["clock_minute"] - max_start
        if delta < REGRESSION_COOLDOWN_MINUTES:
            raise AppError(ERR_REGRESSION_COOLDOWN_ACTIVE,
                           f"Cooldown active; wait {REGRESSION_COOLDOWN_MINUTES - delta} more minutes.",
                           409)
    check_version(body, rr)

    # Update started_at_minute to reflect the actual start? PRD says it's set at queue time;
    # we keep started_at_minute from the queue. But cooldown comparison still uses the prior run's
    # started_at_minute. We DO update started_at_minute to current clock so that future cooldown
    # checks consider this run's start time. PRD §3.10 says started_at_minute "is set to the
    # project's current clock_minute" when queued, but the cooldown is about runs that "actually
    # started". To keep it accurate, update started_at_minute on start.
    db.update("regression_runs", rr_id, {
        "status": RR_RUNNING,
        "started_at_minute": project["clock_minute"],
    }, bump=True)
    return success(regression_run_dto(db.find_by_id("regression_runs", rr_id)))


@bp.post("/regression-runs/<rr_id>/complete")
def complete_regression(rr_id):
    require_role(ROLE_RELEASE_MANAGER)
    body = get_json()
    rr = find_regression_or_404(rr_id)
    d = find_defect_or_404(rr["defect_id"])
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if rr["status"] != RR_RUNNING:
        raise AppError(ERR_REGRESSION_NOT_RUNNING,
                       f"RegressionRun must be RUNNING; was {rr['status']}", 409)

    result = require_enum(body, "result", {RR_PASSED, RR_FAILED})
    check_version(body, rr)

    db.update("regression_runs", rr_id, {
        "ended_at_minute": project["clock_minute"],
        "result": result,
        "status": result,
    }, bump=True)
    append_audit(
        defect_id=d["id"],
        event_type="EXTERNAL_EVENT_SYNC",
        actor_id=g.user_id,
        at_minute=project["clock_minute"],
        external_payload={"system": "CI_CD", "raw": {"run_id": rr_id, "status": result}},
    )

    if result == RR_FAILED and d["status"] == DEFECT_VERIFIED:
        d_fresh = db.find_by_id("defects", d["id"])
        reopen_cascade(d_fresh, project, g.user_id)
        db.update("defects", d["id"], d_fresh, bump=True)

    return success(regression_run_dto(db.find_by_id("regression_runs", rr_id)))


@bp.get("/regression-runs")
def list_regression_runs():
    require_role(ROLE_ANY)
    limit, offset = parse_pagination(request.args)
    filters = {}
    for k in ("defect_id", "module_id", "status"):
        v = request.args.get(k)
        if v:
            filters[k] = v
    rows, total = db.query("regression_runs", filters=filters,
                           limit=limit, offset=offset)
    return success_list([regression_run_dto(r) for r in rows], total, limit, offset)


@bp.get("/regression-runs/<rr_id>")
def get_regression(rr_id):
    require_role(ROLE_ANY)
    rr = find_regression_or_404(rr_id)
    return success(regression_run_dto(rr))
