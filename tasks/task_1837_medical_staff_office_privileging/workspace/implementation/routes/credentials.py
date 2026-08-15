from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import (check_dt_order, get_body, paginate, parse_dt_field,
                  require_enum, require_fields)

bp = Blueprint("credentials", __name__)

COORD = "MedicalStaffCoordinator"
CHAIR = "CredentialsCommitteeChair"

CRED_KINDS = ("STATE_LICENSE", "DEA", "BOARD_CERT", "MALPRACTICE_INSURANCE",
              "ACLS")


def _get_cred(cid):
    rec = db.credentials.get(cid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "ExpirableCredential not found")
    return rec


@bp.route("/mso/expirable-credentials", methods=["POST"])
@require_roles(COORD)
def create_credential():
    body = get_body()
    # Rung 3: existence.
    member_id = body.get("member_id")
    member = None
    if member_id is not None:
        member = db.members.get(member_id)
        if member is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "MedicalStaffMember not found")
    supersedes_id = body.get("supersedes_credential_id")
    if supersedes_id is not None and supersedes_id not in db.credentials:
        errors.raise_err(errors.ERR_NOT_FOUND,
                         "supersedes_credential_id does not exist")
    # Rung 11: input shape.
    require_fields(body, ["member_id", "credential_kind", "credential_number",
                          "issued_on", "expires_on"])
    require_enum(body, "credential_kind", CRED_KINDS)
    if not isinstance(body["credential_number"], str) \
            or not body["credential_number"]:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "credential_number must be a non-empty string")
    check_dt_order(body["issued_on"], body["expires_on"],
                   "issued_on", "expires_on")
    rec = services.base_record()
    rec.update({
        "member_id": member_id,
        "credential_kind": body["credential_kind"],
        "credential_number": body["credential_number"],
        "issued_on": body["issued_on"],
        "expires_on": body["expires_on"],
        "credential_status": "CURRENT",
        "supersedes_credential_id": supersedes_id,
    })
    db.credentials[rec["id"]] = rec
    services.recompute_risk(member)
    return ok_object(serializers.credential(rec), 201)


@bp.route("/mso/expirable-credentials", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_credentials():
    items, limit, offset, total = paginate(
        db.credentials.values(), serializers.credential,
        ["member_id", "credential_kind", "credential_status",
         "supersedes_credential_id"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/expirable-credentials/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_credential(cid):
    return ok_object(serializers.credential(_get_cred(cid)))


@bp.route("/mso/expirable-credentials/<cid>/renew", methods=["POST"])
@require_roles(COORD)
def renew_credential(cid):
    body = get_body()
    old = _get_cred(cid)
    # Rung 5: state.
    if old["credential_status"] != "LAPSED":
        errors.raise_err(errors.ERR_CREDENTIAL_NOT_LAPSED,
                         "Credential is not in LAPSED")
    # New expiry must lie strictly after the current clock.
    expires_raw = body.get("expires_on")
    if expires_raw is not None:
        expires = parse_dt_field(expires_raw, "expires_on")
        if expires <= db.clock_now():
            errors.raise_err(errors.ERR_CREDENTIAL_EXPIRY_PAST,
                             "expires_on must be strictly after the current "
                             "clock")
    # Rung 11: input shape.
    require_fields(body, ["credential_number", "issued_on", "expires_on"])
    if not isinstance(body["credential_number"], str) \
            or not body["credential_number"]:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "credential_number must be a non-empty string")
    check_dt_order(body["issued_on"], body["expires_on"],
                   "issued_on", "expires_on")

    member = db.members.get(old["member_id"])
    old["credential_status"] = "RENEWED"
    services.touch(old)
    rec = services.base_record()
    rec.update({
        "member_id": old["member_id"],
        "credential_kind": old["credential_kind"],
        "credential_number": body["credential_number"],
        "issued_on": body["issued_on"],
        "expires_on": body["expires_on"],
        "credential_status": "CURRENT",
        "supersedes_credential_id": old["id"],
    })
    db.credentials[rec["id"]] = rec
    if member is not None:
        services.reinstate_grants_for_credential(member,
                                                 old["credential_kind"])
        services.recompute_risk(member)
    return ok_object(serializers.credential(rec), 200)


@bp.route("/mso/expirable-credentials/<cid>/revoke", methods=["POST"])
@require_roles(CHAIR)
def revoke_credential(cid):
    get_body()
    cred = _get_cred(cid)
    if cred["credential_status"] != "CURRENT":
        errors.raise_err(errors.ERR_CREDENTIAL_NOT_CURRENT,
                         "Credential is not in CURRENT")
    cred["credential_status"] = "REVOKED"
    services.touch(cred)
    member = db.members.get(cred["member_id"])
    if member is not None:
        # Identical cascade to a lapse.
        if cred["credential_kind"] in services.SUSPENDING_KINDS:
            services.suspend_grants_for_credential(member,
                                                   cred["credential_kind"])
        services.recompute_risk(member)
    return ok_object(serializers.credential(cred))
