"""Supplier endpoints."""
from __future__ import annotations

from flask import Blueprint, current_app

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_UNIQUE_VIOLATION,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
)
from pv_ops.responses import created, success
from pv_ops.services import serializers
from pv_ops.utils import (
    get_body,
    opt_enum,
    opt_int,
    opt_str,
    require_enum,
    require_str,
)


bp = Blueprint("suppliers", __name__)


@bp.route("/pv-ops/suppliers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_supplier():
    body = get_body()
    name = require_str(body, "name")
    contact = require_str(body, "contact")
    rating = opt_enum(body, "rating", {"A", "B", "C"}) or "B"
    store = current_app.extensions["store"]
    with store.lock:
        for s in store.suppliers.values():
            if s.get("name", "").lower() == name.lower():
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Supplier name already exists")
        row = {
            "name": name,
            "contact": contact,
            "rating": rating,
            "lifecycle_state": "ACTIVE",
        }
        store.insert_common(row)
        store.suppliers[row["id"]] = row
        return created(serializers.supplier_view(row))


@bp.route("/pv-ops/suppliers/<supplier_id>", methods=["PATCH"])
@require_roles("PlatformAdmin")
def patch_supplier(supplier_id: str):
    body = get_body()
    store = current_app.extensions["store"]
    with store.lock:
        row = store.suppliers.get(supplier_id)
        if not row:
            raise APIError(ERR_NOT_FOUND, 404, "Supplier not found")
        version = opt_int(body, "version")
        if version is not None and version != row.get("version"):
            raise APIError(ERR_VERSION_CONFLICT, 409, "Version mismatch")
        contact = opt_str(body, "contact")
        rating = opt_enum(body, "rating", {"A", "B", "C"})
        lifecycle = opt_enum(body, "lifecycle_state", {"ACTIVE", "BLACKLISTED"})
        if contact is not None:
            row["contact"] = contact
        if rating is not None:
            row["rating"] = rating
        if lifecycle is not None:
            row["lifecycle_state"] = lifecycle
        store.bump(row)
        return success(serializers.supplier_view(row))
