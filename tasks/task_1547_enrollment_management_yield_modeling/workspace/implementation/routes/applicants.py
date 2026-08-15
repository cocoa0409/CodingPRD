"""Applicant endpoints."""
from flask import Blueprint, request

from db import store, new_id, now_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
    ERR_DUPLICATE_APPLICANT_EMAIL, ERR_APPLICANT_TYPE_DATA_MISSING,
    ERR_READMIT_NOT_ELIGIBLE, ERR_NOT_RESOURCE_OWNER,
)
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.derived import recompute_cycle
from services.serializers import serialize_applicant

bp = Blueprint("applicants", __name__, url_prefix="/enrollment/applicants")


@bp.route("", methods=["POST"])
def create_applicant():
    require_roles("AdmissionsOfficer")
    body = request.get_json(silent=True) or {}
    cycle_id = body.get("cycle_id")
    full_name = body.get("full_name")
    email = body.get("email")
    applicant_type = body.get("applicant_type")
    inquiry_source = body.get("inquiry_source")
    distance_band = body.get("distance_band")
    transfer_credit_hours = body.get("transfer_credit_hours")
    prior_standing = body.get("prior_standing")

    if cycle_id is None or cycle_id not in store.cycles:
        raise ApiError(ERR_NOT_FOUND, 404, "cycle_id not found")
    for v, n in [(full_name, "full_name"), (email, "email"),
                 (applicant_type, "applicant_type"), (inquiry_source, "inquiry_source"),
                 (distance_band, "distance_band")]:
        if v is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{n} required")

    if applicant_type not in ("FIRST_YEAR", "TRANSFER", "READMIT"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "applicant_type invalid")
    if inquiry_source not in ("WEB_FORM", "CAMPUS_VISIT", "COLLEGE_FAIR", "REFERRAL", "PURCHASED_LIST"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "inquiry_source invalid")
    if distance_band not in ("LOCAL", "REGIONAL", "NATIONAL", "INTERNATIONAL"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "distance_band invalid")

    # Uniqueness of email within cycle
    for a in store.applicants.values():
        if a["cycle_id"] == cycle_id and a["email"] == email:
            raise ApiError(ERR_DUPLICATE_APPLICANT_EMAIL, 409,
                           "email already exists in this cycle")

    if applicant_type == "TRANSFER":
        if transfer_credit_hours is None:
            raise ApiError(ERR_APPLICANT_TYPE_DATA_MISSING, 422,
                           "transfer_credit_hours required for TRANSFER")
        if not isinstance(transfer_credit_hours, int) or transfer_credit_hours < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "transfer_credit_hours must be a non-negative integer")
    if applicant_type == "READMIT":
        if prior_standing is None:
            raise ApiError(ERR_APPLICANT_TYPE_DATA_MISSING, 422,
                           "prior_standing required for READMIT")
        if prior_standing not in ("GOOD_STANDING", "ACADEMIC_PROBATION", "DISMISSED"):
            raise ApiError(ERR_INVALID_REQUEST, 400, "prior_standing invalid")
        if prior_standing == "DISMISSED":
            raise ApiError(ERR_READMIT_NOT_ELIGIBLE, 422,
                           "READMIT applicant with DISMISSED prior standing not eligible")

    now = now_iso()
    applicant = {
        "id": new_id(),
        "cycle_id": cycle_id,
        "full_name": full_name,
        "email": email,
        "applicant_type": applicant_type,
        "inquiry_source": inquiry_source,
        "distance_band": distance_band,
        "transfer_credit_hours": transfer_credit_hours,
        "prior_standing": prior_standing,
        "funnel_stage": "INQUIRY",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.applicants[applicant["id"]] = applicant
    cycle = store.cycles.get(cycle_id)
    if cycle:
        recompute_cycle(cycle)
    return success_object(serialize_applicant(applicant), status=201)


@bp.route("/<applicantId>", methods=["GET"])
def get_applicant(applicantId):
    user_id, role = get_auth()
    if role not in ("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer",
                    "FinancialAidOfficer", "Applicant"):
        from errors import ERR_FORBIDDEN
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted")
    a = store.applicants.get(applicantId)
    if not a:
        raise ApiError(ERR_NOT_FOUND, 404, "Applicant not found")
    if role == "Applicant" and user_id != a["id"]:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Not resource owner")
    return success_object(serialize_applicant(a))


@bp.route("", methods=["GET"])
def list_applicants():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "FinancialAidOfficer")
    cycle_id = request.args.get("cycle_id")
    inquiry_source = request.args.get("inquiry_source")
    funnel_stage = request.args.get("funnel_stage")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = list(store.applicants.values())
    if cycle_id:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    if inquiry_source:
        items = [a for a in items if a["inquiry_source"] == inquiry_source]
    if funnel_stage:
        items = [a for a in items if a["funnel_stage"] == funnel_stage]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_applicant(a) for a in page], limit, offset, total)
