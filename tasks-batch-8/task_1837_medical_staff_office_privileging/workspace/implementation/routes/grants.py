from flask import Blueprint, g

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, paginate

bp = Blueprint("grants", __name__)


@bp.route("/mso/privilege-grants", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_grants():
    items, limit, offset, total = paginate(
        db.grants.values(), serializers.grant,
        ["member_id", "delineation_id", "grant_status"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/privilege-grants/<gid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_grant(gid):
    rec = db.grants.get(gid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "PrivilegeGrant not found")
    return ok_object(serializers.grant(rec))


@bp.route("/mso/privilege-grants/<gid>/relinquish", methods=["POST"])
@require_roles("Practitioner")
def relinquish_grant(gid):
    get_body()
    rec = db.grants.get(gid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "PrivilegeGrant not found")
    if rec["grant_status"] not in ("PROVISIONAL", "ACTIVE"):
        errors.raise_err(errors.ERR_GRANT_NOT_RELINQUISHABLE,
                         "Grant is not in PROVISIONAL or ACTIVE")
    # SoD / ownership: the acting Practitioner must be the grant holder
    # (X-User-ID is the acting MedicalStaffMember id for this role).
    if rec["member_id"] != g.user_id:
        errors.raise_err(errors.ERR_NOT_GRANT_HOLDER,
                         "Only the grant holder may relinquish the grant")
    rec["grant_status"] = "RELINQUISHED"
    services.touch(rec)
    member = db.members.get(rec["member_id"])
    if member is not None:
        services.recompute_member_derived(member)
    return ok_object(serializers.grant(rec))
