"""Grantee routes."""

from flask import Blueprint, request
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_CROSS_RESOURCE_MISMATCH,
)
from services.common import (
    init_common, get_body, get_or_404, get_pagination, paginate_list,
    sort_by_created_at_asc, require_string, require_enum,
)
from services.serializers import serialize_grantee


bp = Blueprint("grantees", __name__)
RESIDENCIES = {"US", "UK", "CN", "SG"}


@bp.post("/option-plans/<plan_id>/grantees")
@auth_required(["PlanAdministrator"])
def create_grantee(plan_id):
    plan = get_or_404("option_plans", plan_id)
    body = get_body()
    hr_id = require_string(body, "hr_employee_id")
    name = require_string(body, "full_name")
    residency = require_enum(body, "tax_residency", RESIDENCIES)
    gid = new_id()
    grantee = {
        "id": gid,
        "plan_id": plan_id,
        "hr_employee_id": hr_id,
        "full_name": name,
        "tax_residency": residency,
        "eligibility_status": "ELIGIBLE",
        "departed_at": None,
    }
    init_common(grantee)
    DB["grantees"][gid] = grantee
    return success_response(serialize_grantee(grantee), http_status=201)


@bp.get("/option-plans/<plan_id>/grantees")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "AuditViewer"])
def list_grantees(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    elig = request.args.get("eligibility_status")
    items = [g for g in DB["grantees"].values() if g["plan_id"] == plan_id]
    if elig:
        items = [g for g in items if g["eligibility_status"] == elig]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_grantee(g) for g in sliced], total, limit, offset)
