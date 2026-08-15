"""Counselor endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_int,
    require_list,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("counselors", __name__)


@bp.route("/ucc/counselors", methods=["POST"])
@require_roles("ClinicalDirector")
def create_counselor(_user_id: str, _role: str):
    body = get_json_body()
    license_id = require_string(body, "license_id")
    full_name = require_string(body, "full_name")
    specialties = require_list(body, "specialties")
    weekly_cap = require_int(body, "weekly_individual_capacity", minimum=1)
    max_risk = require_int(body, "max_caseload_risk_points", minimum=1)
    active = optional_field(body, "active", True)
    if not isinstance(active, bool):
        raise_err(ERR_INVALID_REQUEST, "active must be a boolean")

    for c in db.counselors.values():
        if c.get("license_id") == license_id:
            raise_err(ERR_DUPLICATE, "license_id already exists")

    counselor = {
        "license_id": license_id,
        "full_name": full_name,
        "specialties": specialties,
        "weekly_individual_capacity": weekly_cap,
        "max_caseload_risk_points": max_risk,
        "active": active,
    }
    db.stamp_new(counselor)
    db.counselors[counselor["id"]] = counselor
    return success_object(serialize(counselor), 201)


@bp.route("/ucc/counselors/<counselor_id>", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "TriageScreener", "ClinicalDirector", "ReferralCoordinator")
def get_counselor(counselor_id: str, _user_id: str, _role: str):
    c = db.counselors.get(counselor_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, "Counselor id does not exist")
    return success_object(serialize(c))


@bp.route("/ucc/counselors", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "TriageScreener", "ClinicalDirector", "ReferralCoordinator")
def list_counselors(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.counselors.values()))
    # active filter
    from flask import request
    raw_active = request.args.get("active")
    if raw_active is not None and raw_active != "":
        target = raw_active.lower() == "true"
        items = [c for c in items if bool(c.get("active")) == target]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
