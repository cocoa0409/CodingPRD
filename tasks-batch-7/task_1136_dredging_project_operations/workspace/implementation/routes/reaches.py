"""Reach endpoints (PRD 3.1, 3.4)."""
import uuid
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PROJECT_NOT_ACTIVE,
    ERR_PLAN_NOT_APPROVED,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_reach
from util import (
    as_int,
    as_num,
    as_str,
    check,
    get_body,
    new_entity,
    req_present,
    touch,
)

bp = Blueprint("reaches", __name__)


@bp.post("/reaches")
@require_roles("OwnerEngineer")
def create_reach():
    body = get_body()
    project_id = body.get("project_id")
    if project_id is not None and project_id not in store.projects:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    project_id = as_str(req_present(body, "project_id"), "project_id")
    name = as_str(req_present(body, "name"), "name")
    design = as_int(req_present(body, "design_quantity_cy"), "design_quantity_cy")
    check(design > 0, "design_quantity_cy must be > 0")
    depth = as_num(req_present(body, "required_depth_ft"), "required_depth_ft")
    check(depth > 0, "required_depth_ft must be > 0")
    overdepth = as_num(
        req_present(body, "allowable_overdepth_ft"), "allowable_overdepth_ft"
    )
    check(overdepth >= 0, "allowable_overdepth_ft must be >= 0")
    allowance = as_int(
        req_present(body, "overdepth_allowance_cy"), "overdepth_allowance_cy"
    )
    check(allowance >= 0, "overdepth_allowance_cy must be >= 0")
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "name": name,
            "design_quantity_cy": design,
            "required_depth_ft": depth,
            "allowable_overdepth_ft": overdepth,
            "overdepth_allowance_cy": allowance,
            "status": "PENDING",
            "removed_in_place_cy": Decimal("0"),
            "cumulative_certified_quantity_cy": Decimal("0"),
        }
    )
    store.reaches[rec["id"]] = rec
    return ok(serialize_reach(rec), 201)


def _get_reach(rid):
    reach = store.reaches.get(rid)
    if reach is None:
        raise ApiError(ERR_NOT_FOUND, "Reach not found", 404)
    return reach


@bp.get("/reaches/<rid>")
@require_roles(*ALL_ROLES)
def get_reach(rid):
    return ok(serialize_reach(_get_reach(rid)))


@bp.get("/reaches")
@require_roles(*ALL_ROLES)
def list_reaches():
    return list_response(store.reaches, serialize_reach, ["project_id", "status"])


@bp.post("/reaches/<rid>/begin-dredging")
@require_roles("ContractorOps")
def begin_dredging(rid):
    reach = _get_reach(rid)
    # State gate (class 6): PRE_SURVEYED -> DREDGING only.
    if reach["status"] != "PRE_SURVEYED":
        raise ApiError(
            ERR_INVALID_STATE, "Reach must be PRE_SURVEYED to begin dredging", 409
        )
    project = store.projects[reach["project_id"]]
    if project["status"] != "ACTIVE":
        raise ApiError(ERR_PROJECT_NOT_ACTIVE, "Project is not ACTIVE", 409)
    # Referenced-entity state (class 11): an APPROVED plan must exist.
    if not any(
        p["project_id"] == reach["project_id"] and p["status"] == "APPROVED"
        for p in store.plans.values()
    ):
        raise ApiError(ERR_PLAN_NOT_APPROVED, "No APPROVED DredgePlan for the project", 409)
    reach["status"] = "DREDGING"
    touch(reach)
    return ok(serialize_reach(reach))
