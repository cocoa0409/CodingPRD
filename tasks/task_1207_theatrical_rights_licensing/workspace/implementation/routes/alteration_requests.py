"""AlterationRequest routes."""
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_referenced_not_found, err_invalid_request, err_invalid_state,
    err_alteration_prohibited,
)
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services.serializers import alteration_request_out

bp = Blueprint("alteration_requests", __name__)

ALTERATION_KINDS = {"CUT", "GENDER_SWAP", "TEXT_CHANGE", "STAGING_CHANGE", "TRANSLATION"}
RESTRICTED_ALLOWED = {"CUT", "STAGING_CHANGE"}


@bp.post("/licensing/alteration-requests")
def create_alteration_request():
    user_id, role = require_roles("Applicant")
    body = request.get_json(silent=True) or {}
    agreement_id = body.get("agreement_id")
    if not isinstance(agreement_id, str) or not agreement_id:
        raise err_invalid_request("agreement_id is required")
    g = db.agreements.get(agreement_id)
    if not g:
        raise err_referenced_not_found("agreement_id not found")
    check_applicant_owner(user_id, role, g["organization_id"])
    kind = body.get("alteration_kind")
    if kind not in ALTERATION_KINDS:
        raise err_invalid_request("alteration_kind invalid")
    description = body.get("description")
    if not isinstance(description, str):
        raise err_invalid_request("description is required and must be a string")
    now = db.clock_now()
    ar = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "alteration_kind": kind,
        "description": description,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.alteration_requests[ar["id"]] = ar
    return ok_object(alteration_request_out(ar), 201)


@bp.get("/licensing/alteration-requests/<request_id>")
def get_alteration_request(request_id):
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant")
    ar = db.alteration_requests.get(request_id)
    if not ar:
        raise err_not_found("AlterationRequest not found")
    if role == "Applicant":
        g = db.agreements[ar["agreement_id"]]
        check_applicant_owner(user_id, role, g["organization_id"])
    return ok_object(alteration_request_out(ar))


@bp.get("/licensing/alteration-requests")
def list_alteration_requests():
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant")
    limit, offset = parse_pagination(request.args)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    items = list(db.alteration_requests.values())
    if role == "Applicant":
        items = [a for a in items if db.agreements[a["agreement_id"]]["organization_id"] == user_id]
    if agreement_id is not None:
        items = [a for a in items if a["agreement_id"] == agreement_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([alteration_request_out(a) for a in page], limit, offset, total)


@bp.post("/licensing/alteration-requests/<request_id>/approve")
def approve_alteration_request(request_id):
    user_id, role = require_roles("RightsAdmin")
    ar = db.alteration_requests.get(request_id)
    if not ar:
        raise err_not_found("AlterationRequest not found")
    if ar["status"] != "SUBMITTED":
        raise err_invalid_state("AlterationRequest must be SUBMITTED")
    g = db.agreements[ar["agreement_id"]]
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE")
    title = db.titles[g["title_id"]]
    if title["restricted_material"] and ar["alteration_kind"] not in RESTRICTED_ALLOWED:
        raise err_alteration_prohibited()
    ar["status"] = "APPROVED"
    ar["decided_by_user_id"] = user_id
    ar["updated_at"] = db.clock_now()
    ar["version"] += 1
    return ok_object(alteration_request_out(ar))


@bp.post("/licensing/alteration-requests/<request_id>/deny")
def deny_alteration_request(request_id):
    user_id, role = require_roles("RightsAdmin")
    ar = db.alteration_requests.get(request_id)
    if not ar:
        raise err_not_found("AlterationRequest not found")
    if ar["status"] != "SUBMITTED":
        raise err_invalid_state("AlterationRequest must be SUBMITTED")
    ar["status"] = "DENIED"
    ar["decided_by_user_id"] = user_id
    ar["updated_at"] = db.clock_now()
    ar["version"] += 1
    return ok_object(alteration_request_out(ar))
