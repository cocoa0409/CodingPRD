"""Branch endpoints (PRD 3.1, 3.9)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_BRANCH_ORDERS_OPEN, ERR_BRANCH_BACKORDERS_OPEN,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import ALL_READ_ROLES, get_one, list_response, public
from services import (
    compute_pool_units, compute_posture, new_record, settle_program_commitments, touch,
)
from validate import get_body, opt_int, req_bool, req_mmdd, req_str, require_path_resource

bp = Blueprint("branches", __name__)


def ser_branch(b):
    out = public(b)
    out["posture"] = compute_posture(b["id"])
    out["seasonal_pool_units"] = compute_pool_units(b["id"])
    return out


@bp.post("/pool-supply/branches")
def create_branch():
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    body = get_body()
    rec = new_record("branches", {
        "branch_code": req_str(body, "branch_code"),
        "hazmat_storage_certified": req_bool(body, "hazmat_storage_certified"),
        "peak_season_start": req_mmdd(body, "peak_season_start"),
        "peak_season_end": req_mmdd(body, "peak_season_end"),
        "willcall_cutoff_minutes": opt_int(body, "willcall_cutoff_minutes", 90),
        "status": "OPEN",
    })
    return success_object(ser_branch(rec), status=201)


@bp.get("/pool-supply/branches")
def list_branches():
    return list_response("branches", ALL_READ_ROLES, serializer=ser_branch)


@bp.get("/pool-supply/branches/<rid>")
def get_branch(rid):
    return get_one("branches", rid, ALL_READ_ROLES, serializer=ser_branch)


@bp.post("/pool-supply/branches/<rid>/close-season")
def close_season(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    branch = require_path_resource("branches", rid)
    if branch["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "branch season is already closed")
    if any(
        o["branch_id"] == rid and o["fulfillment_status"] in ("CONFIRMED", "PICKED_LOADED")
        for o in db["orders"].values()
    ):
        raise_error(ERR_BRANCH_ORDERS_OPEN, "branch has orders in CONFIRMED or PICKED_LOADED")
    if any(
        b["branch_id"] == rid and b["status"] in ("OPEN", "ALLOCATED")
        for b in db["backorder_requests"].values()
    ):
        raise_error(ERR_BRANCH_BACKORDERS_OPEN, "branch has OPEN or ALLOCATED backorders")
    branch["status"] = "CLOSED_SEASON"
    touch(branch)
    for p in db["seasonal_programs"].values():
        if p["branch_id"] == rid and p["status"] == "OPEN":
            p["status"] = "CLOSED"
            touch(p)
            settle_program_commitments(p)
    return success_object(ser_branch(branch))
