from flask import Blueprint, request

import errors
from db import DB, CLOCK, new_id, stamp_new
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_string, parse_limit_offset,
)
from response import success_object, success_list
from routes.addendums import serialize_ack

bp = Blueprint("subcontractors", __name__)

ESTIMATORS = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"}


def serialize_sub(sub):
    return {
        "id": sub["id"],
        "legal_name": sub["legal_name"],
        "contact_email": sub["contact_email"],
        "license_number": sub["license_number"],
        "current_prequal_status": sub["current_prequal_status"],
        "created_at": sub["created_at"],
        "updated_at": sub["updated_at"],
        "version": sub["version"],
    }


def get_sub_or_404(sub_id):
    sub = DB.subcontractors.get(sub_id)
    if sub is None:
        raise errors.err_subcontractor_not_found()
    return sub


@bp.post("/subcontractors")
def register_subcontractor():
    _, role = get_context()
    require_role(role, {"Anonymous"})
    body = get_json_body()
    reject_unexpected(body, {"legal_name", "contact_email", "license_number"})
    require_fields(body, ["legal_name", "contact_email", "license_number"])
    legal_name = require_string(body, "legal_name")
    contact_email = require_string(body, "contact_email")
    license_number = require_string(body, "license_number")
    for sub in DB.subcontractors.values():
        if sub["license_number"] == license_number:
            raise errors.err_duplicate_license()
    sub = {
        "id": new_id(),
        "legal_name": legal_name,
        "contact_email": contact_email,
        "license_number": license_number,
        "current_prequal_status": "NONE",
    }
    stamp_new(sub)
    sub["_created_at_dt"] = CLOCK.now()
    DB.subcontractors[sub["id"]] = sub
    return success_object(serialize_sub(sub), 201)


@bp.get("/subcontractors")
def list_subcontractors():
    _, role = get_context()
    require_role(role, ESTIMATORS)
    limit, offset = parse_limit_offset(request.args)
    items = sorted(DB.subcontractors.values(), key=lambda s: (s["_created_at_dt"], s["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_sub(s) for s in page], limit, offset, total)


@bp.get("/subcontractors/<sub_id>")
def read_subcontractor(sub_id):
    user_id, role = get_context()
    require_role(role, ESTIMATORS | {"Subcontractor"})
    sub = get_sub_or_404(sub_id)
    if role == "Subcontractor" and sub["id"] != user_id:
        raise errors.err_forbidden_ownership()
    return success_object(serialize_sub(sub))


@bp.get("/subcontractors/<sub_id>/acknowledgments")
def list_sub_acknowledgments(sub_id):
    user_id, role = get_context()
    require_role(role, ESTIMATORS | {"Subcontractor"})
    sub = get_sub_or_404(sub_id)
    if role == "Subcontractor" and sub["id"] != user_id:
        raise errors.err_forbidden_ownership()
    limit, offset = parse_limit_offset(request.args)
    status_f = request.args.get("status")
    items = sorted(
        (a for a in DB.acks.values() if a["subcontractor_id"] == sub_id),
        key=lambda a: (a["_created_at_dt"], a["id"]),
    )
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_ack(a) for a in page], limit, offset, total)
