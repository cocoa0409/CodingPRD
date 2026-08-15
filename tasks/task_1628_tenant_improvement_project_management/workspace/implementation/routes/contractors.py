"""Contractor registry endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_contractor_ownership_by_contractor
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, APIError,
    ERR_INSURANCE_EXPIRED, ERR_INVALID_STATE,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_str, parse_iso8601, to_iso_z, logical_clock_dt,
)

bp = Blueprint("contractors", __name__)


@bp.route("/api/contractors", methods=["POST"])
def create_contractor():
    require_roles("LandlordPM")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["company_name", "license_number", "insurance_expiry_date"])
    if not is_str(body["company_name"]):
        raise invalid_request("company_name must be a string")
    if not is_str(body["license_number"]):
        raise invalid_request("license_number must be a string")
    try:
        exp = parse_iso8601(body["insurance_expiry_date"])
    except Exception:
        raise invalid_request("insurance_expiry_date must be a valid ISO8601 datetime")

    rec = make_common_fields()
    rec.update({
        "company_name": body["company_name"],
        "license_number": body["license_number"],
        "insurance_expiry_date": to_iso_z(exp),
        "qualification_status": "PENDING",
    })
    store.contractors[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/contractors/<id>", methods=["GET"])
def get_contractor(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "ContractorRep")
    rec = store.contractors.get(id)
    if not rec:
        raise not_found("Contractor not found")
    if role == "ContractorRep":
        check_contractor_ownership_by_contractor(user_id, id)
    return success_object(rec)


def _check_insurance_current(contractor):
    exp = parse_iso8601(contractor["insurance_expiry_date"])
    if exp <= logical_clock_dt():
        raise APIError(ERR_INSURANCE_EXPIRED, 422, "Contractor insurance is expired")


@bp.route("/api/contractors/<id>/qualify", methods=["POST"])
def qualify_contractor(id):
    require_roles("LandlordPM")
    rec = store.contractors.get(id)
    if not rec:
        raise not_found("Contractor not found")
    if rec["qualification_status"] != "PENDING":
        raise invalid_state("Contractor is not in PENDING state")
    _check_insurance_current(rec)
    rec["qualification_status"] = "QUALIFIED"
    bump_version(rec)
    return success_object(rec)


@bp.route("/api/contractors/<id>/suspend", methods=["POST"])
def suspend_contractor(id):
    require_roles("LandlordPM")
    rec = store.contractors.get(id)
    if not rec:
        raise not_found("Contractor not found")
    if rec["qualification_status"] != "QUALIFIED":
        raise invalid_state("Contractor is not in QUALIFIED state")
    rec["qualification_status"] = "SUSPENDED"
    bump_version(rec)
    # Cascade: every ACTIVE engagement of this contractor -> SUSPENDED
    for eng in store.contractor_engagements.values():
        if eng["contractor_id"] == id and eng["status"] == "ACTIVE":
            eng["status"] = "SUSPENDED"
            bump_version(eng)
    return success_object(rec)


@bp.route("/api/contractors/<id>/reinstate", methods=["POST"])
def reinstate_contractor(id):
    require_roles("LandlordPM")
    rec = store.contractors.get(id)
    if not rec:
        raise not_found("Contractor not found")
    if rec["qualification_status"] != "SUSPENDED":
        raise invalid_state("Contractor is not in SUSPENDED state")
    _check_insurance_current(rec)
    rec["qualification_status"] = "QUALIFIED"
    bump_version(rec)
    return success_object(rec)


@bp.route("/api/contractors/<id>/revoke", methods=["POST"])
def revoke_contractor(id):
    require_roles("LandlordPM")
    rec = store.contractors.get(id)
    if not rec:
        raise not_found("Contractor not found")
    if rec["qualification_status"] not in ("PENDING", "QUALIFIED"):
        raise invalid_state("Contractor cannot be revoked from current state")
    # From QUALIFIED: blocked while any engagement is ACTIVE
    if rec["qualification_status"] == "QUALIFIED":
        for eng in store.contractor_engagements.values():
            if eng["contractor_id"] == id and eng["status"] == "ACTIVE":
                raise APIError(
                    ERR_INVALID_STATE, 409,
                    "Cannot revoke contractor with ACTIVE engagements"
                )
    rec["qualification_status"] = "REVOKED"
    bump_version(rec)
    return success_object(rec)


@bp.route("/api/contractors/<id>/contractor-engagements", methods=["GET"])
def list_contractor_engagements(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "ContractorRep")
    rec = store.contractors.get(id)
    if not rec:
        raise not_found("Contractor not found")
    if role == "ContractorRep":
        check_contractor_ownership_by_contractor(user_id, id)
    limit, offset = get_pagination_params()
    items = [e for e in store.contractor_engagements.values() if e["contractor_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/contractors/<id>/lien-waivers", methods=["GET"])
def list_contractor_waivers(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "ContractorRep")
    rec = store.contractors.get(id)
    if not rec:
        raise not_found("Contractor not found")
    if role == "ContractorRep":
        check_contractor_ownership_by_contractor(user_id, id)
    limit, offset = get_pagination_params()
    items = [w for w in store.lien_waivers.values() if w["contractor_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
