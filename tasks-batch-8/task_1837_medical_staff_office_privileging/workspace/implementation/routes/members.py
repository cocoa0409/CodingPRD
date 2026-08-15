from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, paginate, parse_dt_field, require_fields

bp = Blueprint("members", __name__)

COORD = "MedicalStaffCoordinator"
MEC = "MedicalExecutiveCommitteeChair"
CHAIR = "CredentialsCommitteeChair"


@bp.route("/mso/members", methods=["POST"])
@require_roles(COORD)
def create_member():
    body = get_body()
    require_fields(body, ["full_name", "npdb_subject_id",
                          "primary_specialty_code"])
    for f in ("full_name", "npdb_subject_id", "primary_specialty_code"):
        if not isinstance(body[f], str) or not body[f]:
            errors.raise_err(errors.ERR_INVALID_REQUEST,
                             f"{f} must be a non-empty string")
    rec = services.base_record()
    rec.update({
        "full_name": body["full_name"],
        "npdb_subject_id": body["npdb_subject_id"],
        "primary_specialty_code": body["primary_specialty_code"],
        "membership_status": "APPLICANT",
        "privilege_posture": "NONE",
        "current_term_start": None,
        "current_term_end": None,
        "active_privilege_line_count": 0,
        "credential_expiry_risk_score": 0,
        "sod_exclusion_tags": [],
    })
    db.members[rec["id"]] = rec
    return ok_object(serializers.member(rec), 201)


@bp.route("/mso/members", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_members():
    items, limit, offset, total = paginate(
        db.members.values(), serializers.member,
        ["membership_status", "privilege_posture"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/members/<mid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_member(mid):
    rec = db.members.get(mid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    return ok_object(serializers.member(rec))


@bp.route("/mso/members/<mid>/reinstate", methods=["POST"])
@require_roles(MEC)
def reinstate_member(mid):
    rec = db.members.get(mid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    if rec["membership_status"] != "SUSPENDED":
        errors.raise_err(errors.ERR_MEMBER_NOT_SUSPENDED,
                         "Member is not SUSPENDED")
    for case in db.cases.values():
        if (case["subject_member_id"] == mid
                and case["case_status"] in services.OPEN_CASE_STATES):
            errors.raise_err(errors.ERR_OPEN_CASE_EXISTS,
                             "An open adverse action case exists for the member")
    rec["membership_status"] = "ACTIVE"
    services.touch(rec)
    services.recompute_member_derived(rec)
    return ok_object(serializers.member(rec))


@bp.route("/mso/members/<mid>/credential-risk", methods=["GET"])
@require_roles(COORD, CHAIR, MEC)
def credential_risk(mid):
    from flask import request
    rec = db.members.get(mid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    as_of_raw = request.args.get("as_of")
    if as_of_raw is not None:
        as_of = parse_dt_field(as_of_raw, "as_of")
        score = services.compute_risk(rec, as_of=as_of)
        variant = "chronological"
    else:
        services.recompute_risk(rec)
        score = rec["credential_expiry_risk_score"]
        variant = "live"
    return ok_object({"risk_score": score, "variant": variant})
