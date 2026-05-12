"""Volunteer + identity + background-check + hours-breakdown endpoints."""
from flask import Blueprint, g, request

import db
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    err,
)
from middleware import auth_required
from pagination import parse_pagination, slice_sorted
from response import list_response, success
from services.audit import emit_sync
from services.occ import check_occ
from validators import as_lat, as_lng, as_str, require_field
from views import view_application, view_volunteer


bp = Blueprint("volunteers", __name__)


@bp.post("/volunteers")
@auth_required(["SkillAdmin"])
def create_volunteer():
    body = request.get_json(silent=True) or {}
    full_name = as_str(require_field(body, "full_name"), "full_name", 1, 100)
    id_number_hash = as_str(require_field(body, "id_number_hash"), "id_number_hash", 1)
    home_lat = as_lat(require_field(body, "home_lat"))
    home_lng = as_lng(require_field(body, "home_lng"))

    with db.lock():
        # Uniqueness on id_number_hash
        for v in db.volunteers.values():
            if v.get("id_number_hash") == id_number_hash:
                raise err(ERR_INVALID_INPUT, "id_number_hash already exists")
        row = {
            "full_name": full_name,
            "id_number_hash": id_number_hash,
            "home_lat": home_lat,
            "home_lng": home_lng,
            "identity_verification_status": "PENDING",
            "background_check_status": "NONE",
            "total_service_hours": 0,
            "total_completed_activities": 0,
            "points_balance": 0,
            "archived_hours": 0,
        }
        db.init_common(row)
        db.volunteers[row["id"]] = row
    return success(view_volunteer(row), status_code=201)


@bp.get("/volunteers/<vid>")
@auth_required(["Volunteer", "Organizer", "SkillAdmin"])
def get_volunteer(vid):
    row = db.volunteers.get(vid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer not found")
    return success(view_volunteer(row))


@bp.post("/volunteers/<vid>/identity:verify")
@auth_required(["SkillAdmin"])
def verify_identity(vid):
    row = db.volunteers.get(vid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer not found")
    body = request.get_json(silent=True) or {}
    check_occ(row, body)
    with db.lock():
        if row["identity_verification_status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "identity status is not PENDING")
        row["identity_verification_status"] = "VERIFIED"
        db.touch(row)
        emit_sync("IM", "VOLUNTEER_VERIFIED", {"volunteer_id": row["id"]})
        emit_sync("IDENTITY_PROVIDER", "VOLUNTEER_VERIFIED", {"volunteer_id": row["id"]})
    return success(view_volunteer(row))


@bp.post("/volunteers/<vid>/identity:reject")
@auth_required(["SkillAdmin"])
def reject_identity(vid):
    row = db.volunteers.get(vid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer not found")
    body = request.get_json(silent=True) or {}
    check_occ(row, body)
    with db.lock():
        if row["identity_verification_status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "identity status is not PENDING")
        row["identity_verification_status"] = "REJECTED"
        db.touch(row)
    return success(view_volunteer(row))


@bp.post("/volunteers/<vid>/background-check:request")
@auth_required(["Volunteer"])
def bg_request(vid):
    row = db.volunteers.get(vid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer not found")
    if row["id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(row, body)
    with db.lock():
        if row["identity_verification_status"] != "VERIFIED":
            # The PRD requires identity VERIFIED OR background_check is not NONE -> INVALID_STATE
            raise err(ERR_INVALID_STATE, "identity not verified or background-check status is not NONE")
        if row["background_check_status"] != "NONE":
            raise err(ERR_INVALID_STATE, "background check status is not NONE")
        row["background_check_status"] = "PENDING"
        db.touch(row)
    return success(view_volunteer(row))


@bp.post("/volunteers/<vid>/background-check:clear")
@auth_required(["SkillAdmin"])
def bg_clear(vid):
    row = db.volunteers.get(vid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer not found")
    body = request.get_json(silent=True) or {}
    check_occ(row, body)
    with db.lock():
        if row["background_check_status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "background check not PENDING")
        row["background_check_status"] = "CLEARED"
        db.touch(row)
    return success(view_volunteer(row))


@bp.post("/volunteers/<vid>/background-check:fail")
@auth_required(["SkillAdmin"])
def bg_fail(vid):
    row = db.volunteers.get(vid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer not found")
    body = request.get_json(silent=True) or {}
    check_occ(row, body)
    with db.lock():
        if row["background_check_status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "background check not PENDING")
        row["background_check_status"] = "FAILED"
        db.touch(row)
    return success(view_volunteer(row))


@bp.get("/volunteers/<vid>/hours")
@auth_required(["Volunteer", "SkillAdmin"])
def get_hours(vid):
    row = db.volunteers.get(vid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer not found")
    if g.user_role == "Volunteer" and row["id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    limit, offset = parse_pagination()
    completed_apps = [a for a in db.applications.values()
                      if a["volunteer_id"] == vid and a["status"] == "COMPLETED"]
    page, total = slice_sorted(completed_apps, limit, offset)
    items = [view_application(a) for a in page]
    data = {
        "items": items,
        "total_service_hours": row.get("total_service_hours", 0),
        "archived_hours": row.get("archived_hours", 0),
        "lifetime_hours": db.round2(
            float(row.get("total_service_hours", 0)) + float(row.get("archived_hours", 0))
        ),
    }
    # Include pagination meta as well by piggybacking on list_response semantics.
    # Use list_response on items but we want the totals embedded — keep as `success`.
    from response import meta_base
    meta = meta_base()
    meta.update({"limit": limit, "offset": offset, "total_count": total,
                 "has_more": (offset + limit) < total})
    body = {"meta": meta, "response_type": "object", "data": data}
    from flask import jsonify
    resp = jsonify(body)
    resp.status_code = 200
    return resp
