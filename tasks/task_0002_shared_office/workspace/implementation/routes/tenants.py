"""Tenant routes."""
from flask import Blueprint

from common import stamp_new, get_json_body, paginate
from db import db
from errors import api_error
from middleware import require_roles
from response import success

bp = Blueprint("tenants", __name__)


@bp.route("/tenants", methods=["POST"])
def create_tenant():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    legal_name = body.get("legal_name")
    if not isinstance(legal_name, str) or not (1 <= len(legal_name) <= 120):
        raise api_error("ERR_INVALID_TIME_WINDOW", "legal_name required, 1..120 chars")
    credit_limit = body.get("credit_limit_cents", 500000)
    if not isinstance(credit_limit, int) or credit_limit < 0:
        raise api_error("ERR_INVALID_TIME_WINDOW", "credit_limit_cents must be non-negative integer")
    tenant = {
        "legal_name": legal_name,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "access_posture": "OPEN",
        "status": "ACTIVE",
    }
    stamp_new(tenant)
    db.tenants[tenant["id"]] = tenant
    return success(tenant, status=201)


@bp.route("/tenants/<tenant_id>", methods=["GET"])
def get_tenant(tenant_id):
    require_roles(["PlatformAdmin", "TenantAdmin", "BillingOfficer"])
    tenant = db.tenants.get(tenant_id)
    if not tenant:
        raise api_error("ERR_NOT_FOUND", "tenant not found")
    return success(tenant)


@bp.route("/tenants", methods=["GET"])
def list_tenants():
    require_roles(["PlatformAdmin", "BillingOfficer"])
    from flask import request
    status = request.args.get("status")
    items = list(db.tenants.values())
    if status:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
