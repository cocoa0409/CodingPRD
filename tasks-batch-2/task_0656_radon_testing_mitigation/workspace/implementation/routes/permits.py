"""Permit endpoints (PRD §3.5)."""

from flask import Blueprint, request

from db import store, format_iso8601_millis
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body, parse_pagination
from response import object_response, array_response
from services import validate
from services.domain import _common_create_fields, public, touch, now_clock
from services.listing import paginate

bp = Blueprint("permits", __name__)

GET_ROLES = {"PlatformAdmin", "ComplianceOfficer", "MitigationDesigner", "CrewLead"}


@bp.route("/permits", methods=["POST"])
def issue_permit():
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    body = get_json_body()

    mitigation_job_id = validate.require_string(body, "mitigation_job_id")
    jurisdiction_code = validate.require_string(body, "jurisdiction_code")
    permit_number = validate.require_string(body, "permit_number")

    # body FK existence (priority 4).
    job = store.mitigation_jobs.get(mitigation_job_id)
    if job is None:
        raise ApiError(
            errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "mitigation_job_id not found."
        )

    # permit_number unique among ISSUED permits within a jurisdiction (priority 14).
    for p in store.permits.values():
        if (
            p["status"] == "ISSUED"
            and p["jurisdiction_code"] == jurisdiction_code
            and p["permit_number"] == permit_number
        ):
            raise ApiError(
                errors.ERR_DUPLICATE_IDENTIFIER,
                409,
                "permit_number already ISSUED in this jurisdiction.",
            )

    ts = now_clock()
    entity = _common_create_fields()
    entity.update(
        {
            "mitigation_job_id": mitigation_job_id,
            "jurisdiction_code": jurisdiction_code,
            "permit_number": permit_number,
            "issued_at_utc": format_iso8601_millis(ts),
            "status": "ISSUED",
        }
    )
    store.permits[entity["id"]] = entity

    # Set the job's denormalized permit_id pointer (PRD §3.5).
    job["permit_id"] = entity["id"]
    touch(job)

    return object_response(public(entity), 201)


@bp.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    permit = store.permits.get(permit_id)
    if permit is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Permit not found.")
    return object_response(public(permit), 200)


@bp.route("/permits", methods=["GET"])
def list_permits():
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "mitigation_job_id": request.args.get("mitigation_job_id"),
        "status": request.args.get("status"),
    }
    items, total = paginate(store.permits, filters, limit, offset)
    return array_response(items, limit, offset, total, 200)


@bp.route("/permits/<permit_id>/revoke", methods=["POST"])
def revoke_permit(permit_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer", "PlatformAdmin"})
    permit = store.permits.get(permit_id)
    if permit is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Permit not found.")

    # state (priority 5): only an ISSUED permit can be revoked.
    if permit["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only an ISSUED permit can be revoked.")

    # cannot revoke after the job is INSTALLED or CLEARED (ERR_PERMIT_LOCKED).
    job = store.mitigation_jobs.get(permit["mitigation_job_id"])
    if job is not None and job["status"] in {"INSTALLED", "CLEARED"}:
        raise ApiError(
            errors.ERR_PERMIT_LOCKED,
            409,
            "Cannot revoke a permit after the install is complete.",
        )

    permit["status"] = "REVOKED"
    touch(permit)

    # Clear the job's permit_id pointer (PRD §3.5).
    if job is not None and job.get("permit_id") == permit_id:
        job["permit_id"] = None
        touch(job)

    return object_response(public(permit), 200)
