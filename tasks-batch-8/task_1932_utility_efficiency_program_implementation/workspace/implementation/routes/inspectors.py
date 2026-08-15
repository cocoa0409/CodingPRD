"""Inspector endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404

bp = Blueprint("inspectors", __name__)


@bp.post("/efficiency/inspectors")
def create_inspector():
    require_roles({"ProgramManager"})
    body = get_body()
    inspector = {
        "full_name": body.get("full_name"),
        "license_number": body.get("license_number"),
        "excluded_contractor_ids": list(body.get("excluded_contractor_ids") or []),
        "status": "ACTIVE",
    }
    db.stamp_new(inspector)
    db.inspectors[inspector["id"]] = inspector
    return success_object(inspector, 201)


@bp.get("/efficiency/inspectors")
def list_inspectors():
    require_roles({"ProgramManager", "Inspector"})
    items = list(db.inspectors.values())
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i.get("status") == status]
    return paginate(items)


@bp.get("/efficiency/inspectors/<inspector_id>")
def get_inspector(inspector_id):
    require_roles({"ProgramManager", "Inspector"})
    return success_object(fetch_or_404(db.inspectors, inspector_id, "Inspector"))
