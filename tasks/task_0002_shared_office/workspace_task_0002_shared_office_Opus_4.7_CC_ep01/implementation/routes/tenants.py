from flask import Blueprint, request

from errors import raise_error, ERR_NOT_FOUND
from response import success
from middleware import require_roles
from util import add_common_fields
from util_pagination import parse_pagination, paginate
from db import db
from services.tenant_service import tenant_view, refresh_tenant

bp = Blueprint("tenants", __name__)


@bp.route("/tenants", methods=["POST"])
def create_tenant():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    if not isinstance(legal_name, str) or not (1 <= len(legal_name) <= 120):
        raise_error(("ERR_INVALID_INPUT", 422), "legal_name must be 1-120 chars")
    credit_limit = body.get("credit_limit_cents", 500000)
    if not isinstance(credit_limit, int) or credit_limit < 0:
        raise_error(("ERR_INVALID_INPUT", 422), "credit_limit_cents must be >= 0")

    tenant = {
        "legal_name": legal_name,
        "credit_limit_cents": credit_limit,
        "status": "ACTIVE",
        "access_posture": "OPEN",
        "outstanding_balance_cents": 0,
    }
    add_common_fields(tenant, db.now(), db.new_id())
    db.tenants[tenant["id"]] = tenant
    return success(tenant_view(tenant), 201)


@bp.route("/tenants/<tenant_id>", methods=["GET"])
def get_tenant(tenant_id):
    require_roles("PlatformAdmin", "TenantAdmin", "BillingOfficer")
    tenant = db.tenants.get(tenant_id)
    if not tenant:
        raise_error(ERR_NOT_FOUND, "Tenant not found")
    # For TenantAdmin, must be their own tenant
    from flask import g
    if g.user_role == "TenantAdmin":
        m = g.acting_member
        if not m or m["tenant_id"] != tenant_id:
            raise_error(("ERR_FORBIDDEN", 403), "Tenant not accessible")
    refresh_tenant(tenant)
    return success(tenant_view(tenant))


@bp.route("/tenants", methods=["GET"])
def list_tenants():
    require_roles("PlatformAdmin", "BillingOfficer")
    status_filter = request.args.get("status")
    limit, offset = parse_pagination()
    items = list(db.tenants.values())
    if status_filter:
        items = [t for t in items if t["status"] == status_filter]
    items.sort(key=lambda t: t["created_at"])
    for t in items:
        refresh_tenant(t)
    page, meta = paginate(items, limit, offset)
    return success([tenant_view(t) for t in page], pagination=meta)
