from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_LICENSE_STATE,
    ERR_INVALID_PSV_STATE,
    ERR_INVALID_REQUEST,
    ERR_LICENSE_NOT_FOUND,
    ERR_MULTISTATE_NON_COMPACT_STATE,
    ERR_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ERR_PSV_STALE,
    ERR_RENEWAL_WINDOW_NOT_OPEN,
    ERR_SEGREGATION_OF_DUTIES,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from services.derived import (
    COMPACT_STATES,
    PSV_VALIDITY_DAYS,
    RENEWAL_WINDOW_DAYS,
    derive_privilege,
    has_fresh_verified_psv,
    invalidate_items_for,
    recompute_posture,
)
from datetime import timedelta

from util import parse_date_loose

bp = Blueprint("licenses", __name__)

LICENSE_CREATE_SCHEMA = {
    "nurse_id": ("string", True, None),
    "state_code": ("string", True, None),
    "license_number": ("string", True, None),
    "license_class": ("string", True, ["RN", "APRN"]),
    "multistate_flag": ("bool", True, None),
    "issued_on": ("date", True, None),
    "expires_on": ("date", True, None),
}

PSV_CREATE_SCHEMA = {
    "license_id": ("string", True, None),
    "channel": ("string", True, ["NURSYS", "BOARD_PORTAL", "MANUAL_REVIEW"]),
}

RECORD_RESULT_SCHEMA = {
    "outcome": ("string", True, ["VERIFIED", "DISCREPANCY", "UNREACHABLE"]),
    "discrepancy_note": ("string", False, None),
}

RENEW_SCHEMA = {
    "new_expires_on": ("date", True, None),
}


def _license_or_404(license_id):
    return get_or_404("licenses", license_id, ERR_NOT_FOUND, "License not found")


@bp.route("/credentialing/state-licenses", methods=["POST"])
def create_license():
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    body = validate_body(get_body(), LICENSE_CREATE_SCHEMA)
    get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    # Safety (stage 8) precedes uniqueness (stage 9).
    if body["multistate_flag"] and body["state_code"] not in COMPACT_STATES:
        raise ApiError(ERR_MULTISTATE_NON_COMPACT_STATE, "multistate_flag requires a compact state_code", 422)
    if any(
        lic for lic in all_entities("licenses")
        if lic["state_code"] == body["state_code"] and lic["license_number"] == body["license_number"]
    ):
        raise ApiError(ERR_DUPLICATE_RESOURCE, "(state_code, license_number) must be unique", 409)
    lic = create_entity("licenses", {
        "nurse_id": body["nurse_id"],
        "state_code": body["state_code"],
        "license_number": body["license_number"],
        "license_class": body["license_class"],
        "multistate_flag": body["multistate_flag"],
        "issued_on": body["issued_on"].isoformat(),
        "expires_on": body["expires_on"].isoformat(),
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "verified_by_user_id": None,
    })
    return success_object(serialize("licenses", lic), 201)


@bp.route("/credentialing/state-licenses", methods=["GET"])
def list_licenses():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("licenses")
    for param in ("nurse_id", "state_code", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [lic for lic in rows if lic[param] == value]
    total = len(rows)
    return success_list([serialize("licenses", lic) for lic in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/state-licenses/<licenseId>", methods=["GET"])
def get_license(licenseId):
    auth_context()
    lic = _license_or_404(licenseId)
    return success_object(serialize("licenses", lic))


@bp.route("/credentialing/state-licenses/<licenseId>/submit", methods=["POST"])
def submit_license(licenseId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    lic = _license_or_404(licenseId)
    if lic["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_LICENSE_STATE, "Only a DRAFT license can be submitted for verification", 409)
    lic["status"] = "PENDING_VERIFICATION"
    touch(lic)
    return success_object(serialize("licenses", lic))


@bp.route("/credentialing/state-licenses/<licenseId>/attest", methods=["POST"])
def attest_license(licenseId):
    user_id, role = auth_context()
    require_role(role, {"PrimarySourceVerifier"})
    lic = _license_or_404(licenseId)
    if lic["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_LICENSE_STATE, "Only a VERIFIED license can be attested", 409)
    if user_id == lic["created_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Attester must differ from the license creator", 403)
    if not has_fresh_verified_psv(lic["id"]):
        raise ApiError(ERR_PSV_STALE, "No fresh VERIFIED primary-source verification on file", 422)
    lic["status"] = "ACTIVE"
    lic["verified_by_user_id"] = user_id
    touch(lic)
    nurse = db.STORES["nurses"].get(lic["nurse_id"])
    if nurse:
        derive_privilege(nurse, reason="LICENSE_CHANGE")
        recompute_posture(nurse)
    return success_object(serialize("licenses", lic))


@bp.route("/credentialing/state-licenses/<licenseId>/renew", methods=["POST"])
def renew_license(licenseId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    lic = _license_or_404(licenseId)
    body = validate_body(get_body(allow_empty=False), RENEW_SCHEMA)
    today = db.current_date()
    if lic["status"] not in ("EXPIRED", "ACTIVE"):
        raise ApiError(ERR_INVALID_LICENSE_STATE, "Only EXPIRED or window-eligible ACTIVE licenses can be renewed", 409)
    if lic["status"] == "ACTIVE":
        days_to_expiry = (parse_date_loose(lic["expires_on"]) - today).days
        if days_to_expiry > RENEWAL_WINDOW_DAYS:
            raise ApiError(ERR_RENEWAL_WINDOW_NOT_OPEN, "Renewal window opens 60 days before expiry", 422)
    if not has_fresh_verified_psv(lic["id"]):
        raise ApiError(ERR_PSV_STALE, "No fresh VERIFIED primary-source verification on file", 422)
    new_expires_on = body["new_expires_on"]
    if new_expires_on <= today:
        raise ApiError(ERR_INVALID_DATE_RANGE, "new_expires_on must be strictly after the current date", 422)
    open_license_discipline = any(
        d for d in all_entities("disciplines")
        if d["license_id"] == lic["id"] and d["scope"] == "LICENSE" and d["status"] == "ADJUDICATED"
    )
    lic["expires_on"] = new_expires_on.isoformat()
    lic["status"] = "ENCUMBERED" if open_license_discipline else "ACTIVE"
    touch(lic)
    nurse = db.STORES["nurses"].get(lic["nurse_id"])
    if nurse:
        derive_privilege(nurse, reason="LICENSE_CHANGE")
        recompute_posture(nurse)
    return success_object(serialize("licenses", lic))


@bp.route("/credentialing/state-licenses/<licenseId>/surrender", methods=["POST"])
def surrender_license(licenseId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    lic = _license_or_404(licenseId)
    if lic["status"] == "SURRENDERED":
        raise ApiError(ERR_INVALID_LICENSE_STATE, "License is already SURRENDERED", 409)
    lic["status"] = "SURRENDERED"
    touch(lic)
    invalidate_items_for(lic["id"])
    nurse = db.STORES["nurses"].get(lic["nurse_id"])
    if nurse:
        derive_privilege(nurse, reason="LICENSE_CHANGE")
        recompute_posture(nurse)
    return success_object(serialize("licenses", lic))


# --- Primary Source Verifications ---------------------------------------------

@bp.route("/credentialing/primary-source-verifications", methods=["POST"])
def create_psv():
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    body = validate_body(get_body(), PSV_CREATE_SCHEMA)
    lic = get_or_404("licenses", body["license_id"], ERR_LICENSE_NOT_FOUND, "license_id does not reference an existing license")
    if lic["status"] not in ("PENDING_VERIFICATION", "VERIFIED", "EXPIRED"):
        raise ApiError(ERR_INVALID_LICENSE_STATE, "A PSV may be requested only for PENDING_VERIFICATION, VERIFIED, or EXPIRED licenses", 409)
    psv = create_entity("psvs", {
        "license_id": lic["id"],
        "channel": body["channel"],
        "status": "REQUESTED",
        "requested_by_user_id": user_id,
        "resolved_by_user_id": None,
        "verified_on": None,
        "valid_through": None,
        "discrepancy_note": None,
    })
    return success_object(serialize("psvs", psv), 201)


@bp.route("/credentialing/primary-source-verifications", methods=["GET"])
def list_psvs():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("psvs")
    for param in ("license_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [p for p in rows if p[param] == value]
    total = len(rows)
    return success_list([serialize("psvs", p) for p in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/primary-source-verifications/<psvId>", methods=["GET"])
def get_psv(psvId):
    auth_context()
    psv = get_or_404("psvs", psvId, ERR_NOT_FOUND, "PSV not found")
    return success_object(serialize("psvs", psv))


@bp.route("/credentialing/primary-source-verifications/<psvId>/record-result", methods=["POST"])
def record_psv_result(psvId):
    user_id, role = auth_context()
    require_role(role, {"PrimarySourceVerifier"})
    psv = get_or_404("psvs", psvId, ERR_NOT_FOUND, "PSV not found")
    body = validate_body(get_body(allow_empty=False), RECORD_RESULT_SCHEMA)
    if body["outcome"] == "DISCREPANCY" and "discrepancy_note" not in body:
        raise ApiError(ERR_INVALID_REQUEST, "discrepancy_note is required when outcome is DISCREPANCY", 400)
    if psv["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_PSV_STATE, "Only a REQUESTED verification can record a result", 409)
    if user_id == psv["requested_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Recorder must differ from the requester", 403)
    lic = db.STORES["licenses"].get(psv["license_id"])
    outcome = body["outcome"]
    psv["resolved_by_user_id"] = user_id
    if outcome == "VERIFIED":
        today = db.current_date()
        psv["status"] = "VERIFIED"
        psv["verified_on"] = today.isoformat()
        psv["valid_through"] = (today + timedelta(days=PSV_VALIDITY_DAYS)).isoformat()
        if body.get("discrepancy_note") is not None:
            psv["discrepancy_note"] = body["discrepancy_note"]
        if lic and lic["status"] == "PENDING_VERIFICATION":
            lic["status"] = "VERIFIED"
            touch(lic)
    elif outcome == "DISCREPANCY":
        psv["status"] = "DISCREPANCY"
        psv["discrepancy_note"] = body["discrepancy_note"]
        if lic and lic["status"] == "PENDING_VERIFICATION":
            lic["status"] = "DRAFT"
            touch(lic)
    else:  # UNREACHABLE
        psv["status"] = "UNREACHABLE"
        if body.get("discrepancy_note") is not None:
            psv["discrepancy_note"] = body["discrepancy_note"]
    touch(psv)
    return success_object(serialize("psvs", psv))
