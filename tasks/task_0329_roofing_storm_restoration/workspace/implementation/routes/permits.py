"""Permit resource: apply, read, list, issue, expire."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
import validators as V

bp = Blueprint("permits", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}


@bp.route("/permits", methods=["POST"])
def create_permit():
    require_role({"ProductionManager"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    municipality = V.require_field(body, "municipality")
    if not isinstance(job_id, str):
        V.missing_field("job_id")
    if not isinstance(municipality, str):
        V.missing_field("municipality")
    V.resolve_fk(db.jobs, job_id)

    ent = common_create_fields(versioned=True)
    ent.update({
        "job_id": job_id,
        "municipality": municipality,
        "permit_number": None,
        "status": "APPLIED",
    })
    with db.lock:
        db.permits[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/permits/<entity_id>", methods=["GET"])
def get_permit(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.permits, entity_id)
    return success(ent, status=200)


@bp.route("/permits", methods=["GET"])
def list_permits():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.permits.values())
    for key in ("job_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/permits/<entity_id>/issue", methods=["POST"])
def issue_permit(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        permit = V.find_or_404(db.permits, entity_id)
        body = get_json_body()
        permit_number = body.get("permit_number")
        # required field present (priority 5)
        if permit_number is None:
            raise ApiError(errors.ERR_MISSING_FIELD, 400,
                           "permit_number is required")
        if not isinstance(permit_number, str):
            raise ApiError(errors.ERR_MISSING_FIELD, 400,
                           "permit_number must be a string")
        # state (priority 7)
        if permit["status"] != "APPLIED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Permit not APPLIED")
        permit["status"] = "ISSUED"
        permit["permit_number"] = permit_number
        touch(permit)
        return success(permit, status=200)


@bp.route("/permits/<entity_id>/expire", methods=["POST"])
def expire_permit(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        permit = V.find_or_404(db.permits, entity_id)
        if permit["status"] != "APPLIED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Permit not APPLIED")
        permit["status"] = "EXPIRED"
        touch(permit)
        return success(permit, status=200)
