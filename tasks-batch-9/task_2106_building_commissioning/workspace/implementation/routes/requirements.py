"""OwnerRequirement endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_OWNER_REP, authenticate, body_json, db, fail, new_row, ok, ok_list,
    paginate, public, q, sorted_rows, touch, v_enum, v_number, v_string,
)
from finders import get_project, get_requirement

bp = Blueprint("requirements", __name__)


@bp.post("/owner-requirements")
def create_requirement():
    authenticate([ROLE_OWNER_REP])
    body = body_json()
    project_id = v_string(body, "project_id")
    metric_key = v_string(body, "metric_key")
    target_value = v_number(body, "target_value", minimum=0)
    tolerance_pct = v_number(body, "tolerance_pct", minimum=0, maximum=100)
    criticality = v_enum(body, "criticality", calc.CRITICALITIES)

    get_project(project_id)

    row = new_row(db.requirements, {
        "project_id": project_id,
        "supersedes_requirement_id": None,
        "metric_key": metric_key,
        "target_value": target_value,
        "tolerance_pct": tolerance_pct,
        "criticality": criticality,
        "revision": 1,
        "status": "DRAFT",
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/owner-requirements")
def list_requirements():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.requirements.values()))
    project_id = q("project_id")
    supersedes = q("supersedes_requirement_id")
    status = q("status")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_requirement_id"] == supersedes]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/owner-requirements/<requirement_id>")
def read_requirement(requirement_id):
    authenticate(ALL_ROLES)
    return ok(public(get_requirement(requirement_id)))


@bp.post("/owner-requirements/<requirement_id>/approve")
def approve_requirement(requirement_id):
    authenticate([ROLE_OWNER_REP])
    row = get_requirement(requirement_id)
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT requirement may be approved.")
    row["status"] = "APPROVED"
    touch(row)
    services.reconcile()
    return ok(public(row))


@bp.post("/owner-requirements/<requirement_id>/revise")
def revise_requirement(requirement_id):
    authenticate([ROLE_OWNER_REP])
    predecessor = get_requirement(requirement_id)
    body = body_json()
    target_value = v_number(body, "target_value", minimum=0)
    tolerance_pct = v_number(body, "tolerance_pct", minimum=0, maximum=100)
    criticality = v_enum(body, "criticality", calc.CRITICALITIES)

    if predecessor["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED requirement may be revised.")

    predecessor["status"] = "SUPERSEDED"
    touch(predecessor)

    row = new_row(db.requirements, {
        "project_id": predecessor["project_id"],
        "supersedes_requirement_id": predecessor["id"],
        "metric_key": predecessor["metric_key"],
        "target_value": target_value,
        "tolerance_pct": tolerance_pct,
        "criticality": criticality,
        "revision": predecessor["revision"] + 1,
        "status": "DRAFT",
    })

    for plan in calc.project_plans(predecessor["project_id"]):
        if predecessor["id"] in plan["pinned_requirement_ids"] and not plan["pin_stale"]:
            plan["pin_stale"] = True
            touch(plan)

    services.reconcile()
    return ok(public(row), 201)
