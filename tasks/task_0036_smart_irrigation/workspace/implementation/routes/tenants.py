"""Tenant CRUD routes."""

from flask import Blueprint, g

from db import DB, LOCK, new_id
from errors import forbidden, not_found
from middleware import require_roles
from response import success_object
from services.common import (
    fetch_or_404,
    get_json_body,
    require_str,
    stamp_create,
)
from services.serializers import tenant_view


bp = Blueprint("tenants", __name__)


@bp.route("/tenants", methods=["POST"])
@require_roles("PlatformAdmin")
def create_tenant():
    body = get_json_body()
    name = require_str(body, "name")
    contact_email = require_str(body, "contact_email")

    with LOCK:
        rec = stamp_create({
            "id": new_id(),
            "name": name,
            "contact_email": contact_email,
            "status": "ACTIVE",
        })
        DB.tenants[rec["id"]] = rec
    return success_object(tenant_view(rec), status=201)


@bp.route("/tenants/<tenant_id>", methods=["GET"])
def read_tenant(tenant_id):
    role = g.role
    if role not in {"PlatformAdmin", "WaterAdmin", "Operator", "Tenant"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.tenants, tenant_id)
        if role == "Tenant":
            # Tenant may only read its own row
            if rec["id"] != g.user_id:
                raise forbidden()
    return success_object(tenant_view(rec))
