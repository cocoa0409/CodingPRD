"""Officer endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_DUPLICATE_KEY, ERR_NOT_FOUND
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.common import (
    apply_page,
    check_enum,
    get_body,
    paginate,
    require_fields,
    require_str,
    sorted_by_created,
)

bp = Blueprint("officers", __name__)

ROLE_TYPES = {"PROBATION", "PAROLE"}


@bp.post("/officers")
@require_roles("CompactAdministrator")
def create_officer():
    body = get_body()
    require_fields(body, ["full_name", "badge_number", "role_type"])
    require_str(body["full_name"], "full_name")
    require_str(body["badge_number"], "badge_number")
    check_enum(body["role_type"], ROLE_TYPES, "role_type")
    active = body.get("active", True)
    if active is None:
        active = True
    from services.common import require_bool

    require_bool(active, "active")

    # Uniqueness of badge_number across officers (ERR_DUPLICATE_KEY, 409).
    for o in db.officers.values():
        if o["badge_number"] == body["badge_number"]:
            raise ApiError(*ERR_DUPLICATE_KEY, "badge_number already exists.")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "full_name": body["full_name"],
            "badge_number": body["badge_number"],
            "role_type": body["role_type"],
            "active": active,
        }
    )
    db.officers[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/officers/<oid>")
@require_roles("CompactAdministrator", "Officer", "SupervisingJudge")
def get_officer(oid):
    rec = db.officers.get(oid)
    if rec is None:
        raise ApiError(*ERR_NOT_FOUND, "Officer not found.")
    return object_response(public(rec), 200)


@bp.get("/officers")
@require_roles("CompactAdministrator", "Officer", "SupervisingJudge")
def list_officers():
    limit, offset = paginate(request.args)
    records = list(db.officers.values())
    role_type = request.args.get("role_type")
    if role_type is not None:
        records = [r for r in records if r["role_type"] == role_type]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)
