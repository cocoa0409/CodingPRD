"""TerminalResource endpoints."""
from flask import Blueprint, request

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import resource_view
from services.common import touch, get_resource_or_404
from validation import (get_body, req_string, req_enum, opt_int, sort_and_page,
                        RESOURCE_TYPES)

bp = Blueprint("resources", __name__)


@bp.post("/terminal-resources")
def create_resource():
    require_roles("TerminalOperator")
    body = get_body()
    resource_code = req_string(body, "resource_code")
    resource_type = req_enum(body, "resource_type", RESOURCE_TYPES)
    concurrent_capacity = opt_int(body, "concurrent_capacity", 1, ge=1)
    # PRD 2.7: concurrent_capacity > 1 is permitted only on a TRUCK_BAY.
    if concurrent_capacity > 1 and resource_type != "TRUCK_BAY":
        raise err("ERR_RESOURCE_TYPE_MISMATCH",
                  "concurrent_capacity > 1 requires resource_type TRUCK_BAY")
    now = CLOCK.now()
    resource = {
        "id": new_id(),
        "resource_code": resource_code,
        "resource_type": resource_type,
        "concurrent_capacity": concurrent_capacity,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.resources[resource["id"]] = resource
    return success_object(resource_view(resource), status=201)


@bp.get("/terminal-resources")
def list_resources():
    current_user()
    rows = list(STORE.resources.values())
    rt = request.args.get("resource_type")
    if rt is not None:
        rows = [r for r in rows if r["resource_type"] == rt]
    st = request.args.get("status")
    if st is not None:
        rows = [r for r in rows if r["status"] == st]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([resource_view(r) for r in page], total, limit, offset)


@bp.get("/terminal-resources/<resourceId>")
def get_resource(resourceId):
    current_user()
    resource = get_resource_or_404(resourceId)
    return success_object(resource_view(resource))


@bp.post("/terminal-resources/<resourceId>/out-of-service")
def out_of_service(resourceId):
    require_roles("TerminalOperator")
    resource = get_resource_or_404(resourceId)
    if resource["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "Resource %s is %s; out-of-service requires ACTIVE"
                  % (resourceId, resource["status"]))
    # Existing SCHEDULED/ARRIVED/IN_PROGRESS movements are NOT displaced.
    resource["status"] = "OUT_OF_SERVICE"
    touch(resource)
    return success_object(resource_view(resource))


@bp.post("/terminal-resources/<resourceId>/return-to-service")
def resource_return_to_service(resourceId):
    require_roles("TerminalOperator")
    resource = get_resource_or_404(resourceId)
    if resource["status"] != "OUT_OF_SERVICE":
        raise err("ERR_INVALID_STATE",
                  "Resource %s is %s; return-to-service requires OUT_OF_SERVICE"
                  % (resourceId, resource["status"]))
    resource["status"] = "ACTIVE"
    touch(resource)
    return success_object(resource_view(resource))
