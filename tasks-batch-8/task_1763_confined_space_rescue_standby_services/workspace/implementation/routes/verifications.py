"""Isolation verifications (PRD section 3.4)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_PERMIT_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
    ERR_VERIFICATION_INVALID_STATE, ERR_VERIFICATION_NOT_FOUND, raise_error,
)
from helpers import (
    body, iso_z, list_response, now_dt, opt_string, reject_unknown, req_enum,
    req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.permits import get_permit
from services import VERIFICATION_TTL

bp = Blueprint("verifications", __name__)

ISOLATION_TYPES = ("VENTILATION", "BLIND_FLANGE", "LOCKOUT_TAGOUT")


def get_verification(verification_id):
    v = db.isolation_verifications.get(verification_id)
    if v is None:
        raise_error(ERR_VERIFICATION_NOT_FOUND, "Isolation verification not found")
    return v


@bp.route("/rescue-ops/entry-permits/<permit_id>/isolation-verifications", methods=["POST"])
def create_verification(permit_id):
    user_id, _, _ = require_auth(("SafetyOfficer",))
    permit = get_permit(permit_id)
    data = body()
    reject_unknown(data, {"isolation_type", "evidence_ref"})
    isolation_type = req_enum(data, "isolation_type", ISOLATION_TYPES)
    evidence_ref = req_string(data, "evidence_ref")
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        raise_error(ERR_PERMIT_INVALID_STATE,
                    "Verifications may be submitted only while the permit is ISSUED or SUSPENDED")
    verification = {
        "permit_id": permit["id"],
        "isolation_type": isolation_type,
        "evidence_ref": evidence_ref,
        "created_by": user_id,
        "verified_by": None,
        "verified_at": None,
        "expires_at": None,
        "status": "PENDING",
    }
    stamp_new(verification)
    db.isolation_verifications[verification["id"]] = verification
    return success_object(serializers.isolation_verification(verification), 201)


@bp.route("/rescue-ops/isolation-verifications", methods=["GET"])
def list_verifications():
    require_auth(ALL_ROLES)
    return list_response(list(db.isolation_verifications.values()),
                         serializers.isolation_verification, {
                             "permit_id": request.args.get("permit_id"),
                             "isolation_type": request.args.get("isolation_type"),
                             "status": request.args.get("status"),
                             "verified_by": request.args.get("verified_by"),
                         })


@bp.route("/rescue-ops/isolation-verifications/<verification_id>", methods=["GET"])
def get_one_verification(verification_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.isolation_verification(get_verification(verification_id)))


@bp.route("/rescue-ops/isolation-verifications/<verification_id>/verify", methods=["POST"])
def verify_verification(verification_id):
    user_id, _, _ = require_auth(("SafetyOfficer",))
    verification = get_verification(verification_id)
    body()
    if verification["status"] != "PENDING":
        raise_error(ERR_VERIFICATION_INVALID_STATE, "Only a PENDING verification can be verified")
    permit = get_permit(verification["permit_id"])
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        raise_error(ERR_PERMIT_INVALID_STATE,
                    "Parent permit must be ISSUED or SUSPENDED to verify")
    if user_id == permit["issued_by"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "The permit issuer may not verify its isolations")
    now = now_dt()
    verification["status"] = "VERIFIED"
    verification["verified_by"] = user_id
    verification["verified_at"] = iso_z(now)
    verification["expires_at"] = iso_z(now + VERIFICATION_TTL)
    touch(verification)
    return success_object(serializers.isolation_verification(verification))


@bp.route("/rescue-ops/isolation-verifications/<verification_id>/void", methods=["POST"])
def void_verification(verification_id):
    user_id, _, _ = require_auth(("SafetyOfficer",))
    verification = get_verification(verification_id)
    data = body()
    reject_unknown(data, {"reason"})
    opt_string(data, "reason")
    if verification["status"] not in ("PENDING", "VERIFIED"):
        raise_error(ERR_VERIFICATION_INVALID_STATE,
                    "Only a PENDING or VERIFIED verification can be voided")
    verification["status"] = "VOIDED"
    touch(verification)
    return success_object(serializers.isolation_verification(verification))
