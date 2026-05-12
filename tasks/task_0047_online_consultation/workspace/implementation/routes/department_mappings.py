"""DepartmentMapping endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_role
from response import success, success_list, parse_pagination
from config import ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN
from services.serializers import serialize


bp = Blueprint("department_mappings", __name__, url_prefix="/consultation/department-mappings")


@bp.post("")
def create_mapping():
    require_role(ROLE_ADMIN)
    body = request.get_json(silent=True) or {}
    record = {
        "department_code": body.get("department_code"),
        "disease_codes": body.get("disease_codes") or [],
        "triage_priority": body.get("triage_priority", 100),
    }
    row = db.insert("department_mappings", record, with_version=False)
    return success(serialize(row), 201)


@bp.get("")
def list_mappings():
    require_role(ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN)
    limit, offset = parse_pagination(request.args)
    rows = db.all_rows("department_mappings")
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)
