"""Personnel routes (PRD 3.1)."""
from flask import Blueprint, request

from common import require_enum, require_fields, require_string, stamp_create
from db import db
from middleware import (ROLE_AUDITOR, ROLE_INSPECTOR, ROLE_QUALITY_ENGINEER,
                        ROLE_QUALITY_MANAGER, authenticate, require_role)
from response import success
from services.helpers import get_or_404
from services.serializers import personnel_out

bp = Blueprint("personnel", __name__)

# Stored Personnel.role values (PRD 2.1 distinguishes these from request roles).
PERSONNEL_ROLES = {"QUALITY_ENGINEER", "QUALITY_MANAGER", "INSPECTOR", "AUDITOR"}


@bp.route("/personnel", methods=["POST"])
def create_personnel():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    body = request.get_json(silent=True) or {}
    require_fields(body, ["full_name", "email", "role"])
    require_string(body["full_name"], "full_name")
    require_string(body["email"], "email")
    require_enum(body["role"], PERSONNEL_ROLES, "role")

    rec = {
        "full_name": body["full_name"],
        "email": body["email"],
        "role": body["role"],
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.personnel[rec["id"]] = rec
    return success(personnel_out(rec), status=201)


@bp.route("/personnel/<rid>", methods=["GET"])
def get_personnel(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER,
                        ROLE_INSPECTOR, ROLE_AUDITOR})
    rec = get_or_404(db.personnel, rid)
    return success(personnel_out(rec))
