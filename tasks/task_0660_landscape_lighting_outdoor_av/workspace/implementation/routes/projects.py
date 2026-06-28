"""LightingProject endpoints (PRD 3.1, 3.4, 3.12).

LightingProject carries TWO parallel state dimensions: design_status
(DRAFT, ZONED, DESIGN_LOCKED) and commercial_status (PRE_QUOTE, QUOTED,
ACCEPTED, INSTALLED, CLOSED), evolving independently.
"""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_customer, get_project
from middleware import get_auth, require_role
from response import success
from services.serialize import ser_project

bp = Blueprint("projects", __name__)

ALL_ROLES = {
    "LightingDesigner",
    "InstallTech",
    "ControlProgrammer",
    "Customer",
    "OperationsAdmin",
}


@bp.post("/projects")
def create_project():
    _, role = get_auth()
    require_role(role, {"LightingDesigner", "OperationsAdmin"})
    body = get_json_body()
    require_fields(body, ["customer_id", "property_address"])
    customer_id = require_string(body, "customer_id")
    property_address = require_string(body, "property_address")
    # Existence of body FK (priority 3).
    get_customer(customer_id)

    record = stamp_new(
        {
            "customer_id": customer_id,
            "property_address": property_address,
            "design_status": "DRAFT",
            "commercial_status": "PRE_QUOTE",
            "fixture_count": 0,
            "total_committed_load_va": 0,
        }
    )
    db.projects[record["id"]] = record
    return success(ser_project(record), status=201)


@bp.get("/projects/<pid>")
def read_project(pid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    p = get_project(pid)
    return success(ser_project(p), status=200)


@bp.get("/projects")
def list_projects():
    _, role = get_auth()
    require_role(role, {"OperationsAdmin", "LightingDesigner"})
    customer_id = request.args.get("customer_id")
    items = list(db.projects.values())
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    data, pagination = paginate(items, ser_project)
    return success(data, status=200, pagination=pagination)


@bp.post("/projects/<pid>/lock-design")
def lock_design(pid):
    _, role = get_auth()
    require_role(role, {"LightingDesigner"})
    p = get_project(pid)
    # State guard (priority 6): must be ZONED.
    if p["design_status"] != "ZONED":
        raise err("ERR_INVALID_STATE", "Design must be ZONED to lock.")
    # Priority 9: every PLANNED fixture on the project must have a zone.
    for f in db.fixtures.values():
        if (
            f["project_id"] == pid
            and f["status"] == "PLANNED"
            and f.get("zone_id") is None
        ):
            raise err("ERR_UNZONED_FIXTURE", "A planned fixture has no zone.")
    p["design_status"] = "DESIGN_LOCKED"
    touch(p)
    return success(ser_project(p), status=200)


@bp.post("/projects/<pid>/close")
def close_project(pid):
    _, role = get_auth()
    require_role(role, {"OperationsAdmin"})
    p = get_project(pid)
    if p["commercial_status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Project must be INSTALLED to close.")
    # Priority business rule: no PENDING/ADJUSTING service plan.
    for sp in db.service_plans.values():
        if sp["project_id"] == pid and sp["status"] in {"PENDING", "ADJUSTING"}:
            raise err(
                "ERR_PLAN_BLOCKS_CLOSE",
                "A service plan is PENDING or ADJUSTING.",
            )
    p["commercial_status"] = "CLOSED"
    touch(p)
    return success(ser_project(p), status=200)
