"""Doctor endpoints."""

from __future__ import annotations

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success, success_list, parse_pagination
from errors import AppError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_REF_NOT_FOUND
from config import ROLE_DOCTOR, ROLE_PATIENT, ROLE_ADMIN
from services.serializers import serialize
from services.occ import check_version


bp = Blueprint("doctors", __name__, url_prefix="/consultation/doctors")


def _doctor_or_404(did):
    row = db.find_by_id("doctors", did)
    if not row:
        raise AppError(ERR_NOT_FOUND, "Doctor not found.", 404)
    return row


@bp.post("")
def create_doctor():
    require_role(ROLE_ADMIN)
    body = request.get_json(silent=True) or {}
    dept = body.get("department_code")
    # Department must exist as a DepartmentMapping.
    if not db.find_one("department_mappings", department_code=dept):
        raise AppError(ERR_REF_NOT_FOUND, "department_code is not registered.", 422)
    record = {
        "full_name": body.get("full_name"),
        "hospital_id": body.get("hospital_id"),
        "department_code": dept,
        "specialty_codes": body.get("specialty_codes") or [],
        "licensed_region_codes": body.get("licensed_region_codes") or [],
        "status": body.get("status") or "AVAILABLE",
        "max_concurrent_sessions": body.get("max_concurrent_sessions", 1),
        "rating_score": body.get("rating_score", 0.00),
        "base_fee": body.get("base_fee", 50.00),
    }
    row = db.insert("doctors", record)
    return success(serialize(row), 201)


@bp.get("/<did>")
def get_doctor(did):
    require_role(ROLE_DOCTOR, ROLE_PATIENT, ROLE_ADMIN)
    row = _doctor_or_404(did)
    return success(serialize(row), 200)


@bp.patch("/<did>")
def update_doctor(did):
    require_role(ROLE_DOCTOR, ROLE_ADMIN)
    row = _doctor_or_404(did)
    if g.role == ROLE_DOCTOR and g.user_id != row["id"]:
        raise AppError(ERR_FORBIDDEN, "Doctor may only update own row.", 403)
    body = request.get_json(silent=True) or {}
    check_version(row, body)
    updates = {}
    for k in ("status", "max_concurrent_sessions"):
        if k in body:
            updates[k] = body[k]
    row = db.update("doctors", did, updates)
    return success(serialize(row), 200)


@bp.get("")
def list_doctors():
    require_role(ROLE_PATIENT, ROLE_ADMIN, ROLE_DOCTOR)
    limit, offset = parse_pagination(request.args)
    filters = {}
    for k in ("department_code", "hospital_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    # region_code filter is a list-contains check.
    region = request.args.get("region_code")
    rows = db.all_rows("doctors")
    if filters:
        rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    if region:
        rows = [r for r in rows if region in (r.get("licensed_region_codes") or [])]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)
