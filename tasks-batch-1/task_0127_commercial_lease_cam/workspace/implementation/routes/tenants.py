"""Tenant endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import auth_required, ALL_ROLES, PROPERTY_MANAGER, ACCOUNTANT
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_str,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_common_fields

bp = Blueprint("tenants", __name__)


@bp.post("/tenants")
def create_tenant():
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    body = get_body()
    require_fields(body, ["legal_name", "contact_email"])
    if not is_str(body["legal_name"]) or not body["legal_name"]:
        raise APIError(ERR_INVALID_REQUEST, 400, "legal_name must be a non-empty string")
    if not is_str(body["contact_email"]) or not body["contact_email"]:
        raise APIError(ERR_INVALID_REQUEST, 400, "contact_email must be a non-empty string")
    tenant = {
        **new_common_fields(),
        "legal_name": body["legal_name"],
        "contact_email": body["contact_email"],
    }
    db.tenants[tenant["id"]] = tenant
    return ok_object(serialize(tenant), http_status=201)


@bp.get("/tenants/<tid>")
def get_tenant(tid):
    auth_required(ALL_ROLES)()
    t = db.tenants.get(tid)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Tenant not found")
    return ok_object(serialize(t))


@bp.get("/tenants/<tid>/leases")
def list_tenant_leases(tid):
    auth_required(ALL_ROLES)()
    if db.tenants.get(tid) is None:
        raise APIError(ERR_NOT_FOUND, 404, "Tenant not found")
    limit, offset = parse_pagination()
    items = order_by_created([l for l in db.leases.values() if l["tenant_id"] == tid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
