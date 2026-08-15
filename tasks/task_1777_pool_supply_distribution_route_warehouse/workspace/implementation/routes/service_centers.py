"""Service center endpoints (PRD 3.8)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import ALL_READ_ROLES, get_one, list_response, public
from services import new_record, touch
from validate import get_body, req_int, req_str, require_path_resource

bp = Blueprint("service_centers", __name__)

CENTER_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.post("/pool-supply/service-centers")
def create_center():
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    body = get_body()
    center_name = req_str(body, "center_name")
    region_code = req_str(body, "region_code")
    brands = body.get("authorized_brands")
    if not isinstance(brands, list) or any(not isinstance(b, str) for b in brands):
        raise_error(ERR_INVALID_REQUEST, "authorized_brands must be an array of strings")
    rec = new_record("service_centers", {
        "center_name": center_name,
        "region_code": region_code,
        "authorized_brands": list(brands),
        "labor_rate_cents": req_int(body, "labor_rate_cents", minimum=0),
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/pool-supply/service-centers")
def list_centers():
    filters = {
        "region_code": request.args.get("region_code"),
        "status": request.args.get("status"),
    }
    return list_response("service_centers", ALL_READ_ROLES, filters)


@bp.get("/pool-supply/service-centers/<rid>")
def get_center(rid):
    return get_one("service_centers", rid, ALL_READ_ROLES)


@bp.patch("/pool-supply/service-centers/<rid>")
def patch_center(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    center = require_path_resource("service_centers", rid)
    body = get_body()
    changed = False
    if "status" in body and body["status"] is not None:
        v = body["status"]
        if not isinstance(v, str) or v not in CENTER_STATUSES:
            raise_error(ERR_INVALID_REQUEST, "status must be ACTIVE or SUSPENDED")
        if center["status"] != v:
            center["status"] = v
            changed = True
    if "labor_rate_cents" in body and body["labor_rate_cents"] is not None:
        v = body["labor_rate_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise_error(ERR_INVALID_REQUEST, "labor_rate_cents must be a non-negative integer")
        if center["labor_rate_cents"] != v:
            center["labor_rate_cents"] = v
            changed = True
    if changed:
        touch(center)
    return success_object(public(center))
