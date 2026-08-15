"""School endpoints (PRD §3.7)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_EMAIL_TAKEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SCHOOL_NOT_FOUND,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_school
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_list,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("schools", __name__)

SCHOOL_TARGET_STATUSES = {"ACTIVE", "INACTIVE"}


def _load_school(school_id: str) -> dict:
    school = db.schools.get(school_id)
    if school is None:
        raise_err(ERR_SCHOOL_NOT_FOUND, "No school with the given id")
    return school


@bp.route("/library-network/schools", methods=["POST"])
@require_roles("NetworkAdmin")
def create_school(_user_id, _role):
    body = get_json_body()
    contact_email = body.get("contact_email")
    if isinstance(contact_email, str) and contact_email != "":
        for s in db.schools.values():
            if s["contact_email"] == contact_email:
                raise_err(ERR_EMAIL_TAKEN, "Another school already uses this contact email")

    name = require_string(body, "name")
    district_code = require_string(body, "district_code")
    contact_email = require_string(body, "contact_email")
    region_code = require_string(body, "region_code")
    restricted = require_list(body, "restricted_categories")
    for cat in restricted:
        if not isinstance(cat, str) or cat not in domain.BOOK_CATEGORIES:
            raise_err(ERR_INVALID_REQUEST, "restricted_categories must be book categories")

    school = {
        "name": name,
        "district_code": district_code,
        "contact_email": contact_email,
        "region_code": region_code,
        "restricted_categories": list(restricted),
        "status": "REGISTERED",
    }
    db.stamp_new(school)
    db.schools[school["id"]] = school
    return success_object(serialize_school(school), 201)


@bp.route("/library-network/schools", methods=["GET"])
@require_roles("Steward", "SchoolLiaison", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_schools(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_school(s) for s in sort_by_created_at(list(db.schools.values()))]
    items = apply_filters(items, ["status", "region_code"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/schools/<school_id>", methods=["GET"])
@require_roles("Steward", "SchoolLiaison", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_school(school_id: str, _user_id, _role):
    return success_object(serialize_school(_load_school(school_id)))


@bp.route("/library-network/schools/<school_id>/status", methods=["POST"])
@require_roles("NetworkAdmin")
def school_status(school_id: str, _user_id, _role):
    school = _load_school(school_id)
    body = get_json_body()
    target = body.get("target_status")

    if target == "ACTIVE":
        if school["status"] not in ("REGISTERED", "INACTIVE"):
            raise_err(ERR_INVALID_STATE, "School cannot transition to ACTIVE from its current state")
    elif target == "INACTIVE":
        if school["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "School is not in ACTIVE status")

    target = require_enum(body, "target_status", SCHOOL_TARGET_STATUSES)
    school["status"] = target
    db.touch(school)
    return success_object(serialize_school(school))
