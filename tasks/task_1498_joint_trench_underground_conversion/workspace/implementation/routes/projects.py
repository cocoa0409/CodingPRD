"""Project endpoints: create/list/get, lifecycle actions, replan (OCC)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_POSTURE_FROZEN,
    ERR_MIN_PARTICIPANTS,
    ERR_SHARE_SUM_INVALID,
    ERR_DUPLICATE_SEQUENCE,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import project_view
from util import (
    get_json_body,
    optional_int,
    parse_pagination,
    paginate,
    query_arg,
    sort_created,
    require_field,
    require_int,
    require_string,
    require_ts,
    get_or_404,
)

bp = Blueprint("projects", __name__, url_prefix="/api/projects")

PM = "ProgramManager"
ANY = "Any"

LIFECYCLE_ACTIONS = {
    "MOBILIZE",
    "START_TRENCHING",
    "START_CONVERSION",
    "START_RECONCILIATION",
    "CLOSE",
    "CANCEL",
}


@bp.route("", methods=["POST"])
@require_roles(PM)
def create_project(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    rule20_credit_cents = require_int(body, "rule20_credit_cents", minimum=0)
    estimated_total_cost_cents = require_int(body, "estimated_total_cost_cents", minimum=1)
    target_cutover_on = require_ts(body, "target_cutover_on")
    contingency_days = optional_int(body, "contingency_days", 0, minimum=0)

    project = stamp_new({
        "name": name,
        "rule20_credit_cents": rule20_credit_cents,
        "estimated_total_cost_cents": estimated_total_cost_cents,
        "contingency_days": contingency_days,
        "target_cutover_on": target_cutover_on,
        "status": "PLANNING",
        "latest_true_up_run_id": None,
    })
    db.projects[project["id"]] = project
    return success_object(project_view(project), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_projects(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.projects.values())
    status = query_arg("status")
    posture = query_arg("posture")
    if status:
        items = [p for p in items if p["status"] == status]
    if posture:
        items = [p for p in items if domain.compute_posture(p) == posture]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([project_view(p) for p in page], limit, offset, total)


@bp.route("/<pid>", methods=["GET"])
@require_roles(ANY)
def get_project(pid: str, _user_id: str, _role: str):
    project = get_or_404(db.projects, pid, "Project")
    return success_object(project_view(project))


@bp.route("/<pid>/lifecycle", methods=["POST"])
@require_roles(PM)
def lifecycle(pid: str, _user_id: str, _role: str):
    project = get_or_404(db.projects, pid, "Project")
    body = get_json_body()
    action = require_field(body, "action")
    if not isinstance(action, str) or action not in LIFECYCLE_ACTIONS:
        raise_err(ERR_VALIDATION, f"action must be one of {sorted(LIFECYCLE_ACTIONS)}")

    status = project["status"]

    if action == "MOBILIZE":
        if status != "PLANNING":
            raise_err(ERR_INVALID_STATE, "MOBILIZE requires project in PLANNING")
        parts = domain.project_participations(pid)
        committed = [p for p in parts if p["status"] == "COMMITTED"]
        if len(committed) < 2:
            raise_err(ERR_MIN_PARTICIPANTS,
                      "MOBILIZE requires at least 2 COMMITTED participations")
        active = [p for p in parts if p["status"] != "WITHDRAWN"]
        seen = set()
        for p in active:
            if p["sequence_order"] in seen:
                raise_err(ERR_DUPLICATE_SEQUENCE,
                          "sequence_order duplicated among non-withdrawn participations")
            seen.add(p["sequence_order"])
        share_sum = sum(p["cost_share_bp"] for p in parts
                        if p["status"] in {"COMMITTED", "MOBILIZED"})
        if share_sum != 10000:
            raise_err(ERR_SHARE_SUM_INVALID,
                      "cost_share_bp over COMMITTED|MOBILIZED participations "
                      f"sums to {share_sum}, not 10000")
        project["status"] = "MOBILIZED"
        touch(project)
        domain.recompute_provisional(project)

    elif action == "START_TRENCHING":
        if status != "MOBILIZED":
            raise_err(ERR_INVALID_STATE, "START_TRENCHING requires project MOBILIZED")
        if not any(s["status"] == "SCHEDULED" for s in domain.project_segments(pid)):
            raise_err(ERR_INVALID_STATE,
                      "START_TRENCHING requires at least one SCHEDULED segment")
        if domain.compute_posture(project) == "FROZEN":
            raise_err(ERR_POSTURE_FROZEN, "project posture is FROZEN")
        project["status"] = "TRENCHING"
        touch(project)

    elif action == "START_CONVERSION":
        if status != "TRENCHING":
            raise_err(ERR_INVALID_STATE, "START_CONVERSION requires project TRENCHING")
        for s in domain.project_segments(pid):
            if s["status"] not in {"BACKFILLED", "CLOSED"}:
                raise_err(ERR_INVALID_STATE,
                          "every trench segment must be BACKFILLED|CLOSED")
        project["status"] = "CONVERTING"
        touch(project)

    elif action == "START_RECONCILIATION":
        if status != "CONVERTING":
            raise_err(ERR_INVALID_STATE,
                      "START_RECONCILIATION requires project CONVERTING")
        for c in db.conversions.values():
            if c["project_id"] == pid and c["work_status"] != "COMPLETE":
                raise_err(ERR_INVALID_STATE,
                          "every service conversion must be COMPLETE")
        for s in domain.project_segments(pid):
            if s["status"] != "CLOSED":
                raise_err(ERR_INVALID_STATE, "every trench segment must be CLOSED")
        for o in db.outages.values():
            if o["project_id"] == pid and o["status"] not in {"CLOSED", "CANCELLED"}:
                raise_err(ERR_INVALID_STATE,
                          "every outage window must be CLOSED|CANCELLED")
        project["status"] = "RECONCILIATION"
        touch(project)

    elif action == "CLOSE":
        if status != "RECONCILIATION":
            raise_err(ERR_INVALID_STATE, "CLOSE requires project RECONCILIATION")
        run_id = project.get("latest_true_up_run_id")
        run = db.trueup_runs.get(run_id) if run_id else None
        if run is None or run["status"] != "SETTLED":
            raise_err(ERR_INVALID_STATE,
                      "latest true-up run must exist and be SETTLED")
        project["status"] = "CLOSED"
        touch(project)

    elif action == "CANCEL":
        if status not in {"PLANNING", "MOBILIZED"}:
            raise_err(ERR_INVALID_STATE,
                      "CANCEL requires project PLANNING|MOBILIZED")
        # Administrative: participations in INVITED|COMMITTED are left unchanged.
        project["status"] = "CANCELLED"
        touch(project)

    return success_object(project_view(project))


@bp.route("/<pid>/replan", methods=["POST"])
@require_roles(PM)
def replan(pid: str, _user_id: str, _role: str):
    project = get_or_404(db.projects, pid, "Project")
    body = get_json_body()
    new_target = require_ts(body, "new_target_cutover_on")
    expected = require_int(body, "expected_project_version")
    if expected != project["version"]:
        raise_err(ERR_STALE_VERSION,
                  f"expected_project_version {expected} != current {project['version']}")
    project["target_cutover_on"] = new_target
    touch(project)
    return success_object(project_view(project))
