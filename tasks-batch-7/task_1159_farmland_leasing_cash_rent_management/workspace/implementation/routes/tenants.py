from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import require_string, require_int, parse_pagination
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch
from services.serialize import serialize
from services.sweeps import suspend_tenant

bp = Blueprint("tenants", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
TENANT_STATUSES = {"APPLICANT", "APPROVED", "SUSPENDED"}


@bp.route("/tenants", methods=["POST"])
def create_tenant():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    name = require_string(body, "name")
    years = require_int(body, "years_experience", minimum=0)
    rec = new_common()
    rec.update({
        "name": name,
        "years_experience": years,
        "status": "APPLICANT",
        "compliance_score": 100,
    })
    db.tenants[rec["id"]] = rec
    return success_object(serialize("tenant", rec), status=201)


@bp.route("/tenants/<tenantId>", methods=["GET"])
def get_tenant(tenantId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.tenants.get(tenantId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Tenant {tenantId} not found")
    return success_object(serialize("tenant", rec))


@bp.route("/tenants", methods=["GET"])
def list_tenants():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.tenants.values(), key=lambda r: r["created_at"])
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("tenant", r) for r in page], limit, offset, total)


@bp.route("/tenants/<tenantId>/approve", methods=["POST"])
def approve_tenant(tenantId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.tenants.get(tenantId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Tenant {tenantId} not found")
    if rec["status"] not in ("APPLICANT", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Tenant in state {rec['status']} cannot be approved")
    rec["status"] = "APPROVED"
    touch(rec)
    return success_object(serialize("tenant", rec))


@bp.route("/tenants/<tenantId>/suspend", methods=["POST"])
def suspend_tenant_route(tenantId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.tenants.get(tenantId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Tenant {tenantId} not found")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Tenant in state {rec['status']} cannot be suspended")
    suspend_tenant(rec)
    return success_object(serialize("tenant", rec))
