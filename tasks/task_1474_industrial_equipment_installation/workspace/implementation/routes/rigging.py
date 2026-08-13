"""RiggingPlan endpoints: OCC-guarded create-with-supersede, review cycle, revise loop."""
from flask import Blueprint

import db
from errors import (ApiError, ERR_INVALID_STATE, ERR_LIFT_WEIGHT_EXCEEDED,
                    ERR_RIGGING_PLAN_OPEN_EXISTS, ERR_SITE_SURVEY_NOT_ACCEPTED,
                    ERR_STALE_VERSION)
from helpers import project_or_404, rigging_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import rigging_json
from util import new_id, now_iso
from validators import get_body, opt_num, opt_str, pagination, req_enum, req_int, req_num, req_str

bp = Blueprint("rigging_plans", __name__)


@bp.post("/v1/rigging-plans")
@require_roles("SiteSupervisor")
def create_rigging_plan():
    body = get_body()
    # existence (priority 3)
    pid = body.get("project_id")
    project = project_or_404(pid) if isinstance(pid, str) else None
    # OCC (priority 4): expected_project_version vs current Project.version
    epv = body.get("expected_project_version")
    if project is not None and isinstance(epv, int) and not isinstance(epv, bool):
        if epv != project["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           "expected_project_version does not match current project version")
    # schema (priority 7)
    req_str(body, "project_id")
    req_int(body, "expected_project_version")
    weight_raw, weight_d = req_num(body, "lift_weight_tons", gt=0)
    crane_model = req_str(body, "crane_model")
    cap_raw, cap_d = req_num(body, "planned_crane_capacity_tons", gt=0)
    rigging_config = req_enum(body, "rigging_config", ("SINGLE_CRANE", "TANDEM", "GANTRY"))
    # priority 29 (last): at most one open (DRAFT/SUBMITTED) plan per project
    if any(r["project_id"] == project["id"] and r["status"] in ("DRAFT", "SUBMITTED")
           for r in db.rigging_plans.values()):
        raise ApiError(ERR_RIGGING_PLAN_OPEN_EXISTS, 409,
                       "a rigging plan in DRAFT or SUBMITTED already exists for the project")
    prior_count = sum(1 for r in db.rigging_plans.values()
                      if r["project_id"] == project["id"])
    ts = now_iso()
    r = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": project["id"],
        "revision": prior_count + 1,
        "lift_weight_tons": weight_raw,
        "crane_model": crane_model,
        "planned_crane_capacity_tons": cap_raw,
        "rigging_config": rigging_config,
        # weight_check_passed computed at creation; equality passes
        "weight_check_passed": bool(weight_d <= cap_d),
        "status": "DRAFT",
        "reviewer_note": None,
        "_seq": db.next_seq(),
    }
    db.rigging_plans[r["id"]] = r
    # Supersede cascade (PRD 3.4): only when a plan is currently APPROVED/pinned
    if project["approved_rigging_plan_id"] is not None:
        old = db.rigging_plans.get(project["approved_rigging_plan_id"])
        if old is not None and old["status"] == "APPROVED":
            old["status"] = "SUPERSEDED"
            touch(old)
        project["approved_rigging_plan_id"] = None
        project["approved_rigging_plan_revision"] = None
        # every ISSUED lift permit of the project loses its approval basis
        for l in db.lift_permits.values():
            if l["project_id"] == project["id"] and l["status"] == "ISSUED":
                l["status"] = "CANCELLED"
                touch(l)
        touch(project)
    return success(rigging_json(r), 201)


@bp.get("/v1/projects/<pid>/rigging-plans")
@require_roles(*ROLES)
def list_rigging_plans(pid):
    project_or_404(pid)
    limit, offset = pagination()
    items = sorted_items(r for r in db.rigging_plans.values() if r["project_id"] == pid)
    total = len(items)
    return success_list([rigging_json(r) for r in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/rigging-plans/<rid>/submit")
@require_roles("SiteSupervisor")
def submit_rigging_plan(rid):
    r = rigging_or_404(rid)
    if r["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "only a DRAFT rigging plan can be submitted")
    r["status"] = "SUBMITTED"
    touch(r)
    return success(rigging_json(r))


@bp.post("/v1/rigging-plans/<rid>/review")
@require_roles("ProjectManager")
def review_rigging_plan(rid):
    r = rigging_or_404(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a SUBMITTED rigging plan can be reviewed")
    body = get_body()
    outcome = req_enum(body, "outcome", ("APPROVED", "REJECTED"))
    note = opt_str(body, "reviewer_note")
    if outcome == "APPROVED":
        # priority 10: an ACCEPTED site survey must exist for the project
        if not any(s["project_id"] == r["project_id"] and s["status"] == "ACCEPTED"
                   for s in db.site_surveys.values()):
            raise ApiError(ERR_SITE_SURVEY_NOT_ACCEPTED, 409,
                           "no ACCEPTED site survey for the project")
        # priority 20
        if not r["weight_check_passed"]:
            raise ApiError(ERR_LIFT_WEIGHT_EXCEEDED, 409,
                           "lift weight exceeds planned crane capacity")
        r["status"] = "APPROVED"
        # version pin: project pins the approved plan id + revision
        project = db.projects[r["project_id"]]
        project["approved_rigging_plan_id"] = r["id"]
        project["approved_rigging_plan_revision"] = r["revision"]
        touch(project)
    else:
        r["status"] = "REJECTED"
    r["reviewer_note"] = note
    touch(r)
    return success(rigging_json(r))


@bp.post("/v1/rigging-plans/<rid>/revise")
@require_roles("SiteSupervisor")
def revise_rigging_plan(rid):
    r = rigging_or_404(rid)
    if r["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a REJECTED rigging plan can be revised")
    body = get_body()
    weight_raw, weight_d = opt_num(body, "lift_weight_tons", gt=0)
    cap_raw, cap_d = opt_num(body, "planned_crane_capacity_tons", gt=0)
    crane_model = opt_str(body, "crane_model")
    if "rigging_config" in body and body["rigging_config"] is not None:
        r["rigging_config"] = req_enum(body, "rigging_config",
                                       ("SINGLE_CRANE", "TANDEM", "GANTRY"))
    if weight_raw is not None:
        r["lift_weight_tons"] = weight_raw
    if cap_raw is not None:
        r["planned_crane_capacity_tons"] = cap_raw
    if crane_model is not None:
        r["crane_model"] = crane_model
    # recompute weight check (equality passes)
    from util import D
    r["weight_check_passed"] = bool(D(r["lift_weight_tons"]) <= D(r["planned_crane_capacity_tons"]))
    r["status"] = "DRAFT"
    touch(r)
    return success(rigging_json(r))
