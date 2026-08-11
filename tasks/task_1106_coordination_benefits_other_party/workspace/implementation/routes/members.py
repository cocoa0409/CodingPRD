"""Member endpoints."""

from flask import Blueprint, request

from db import stores
from errors import raise_err, ERR_OPEN_CLAIMS_EXIST, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from helpers import (
    base_record, touch, get_or_404, body, req_str, opt_str, opt_int, opt_bool,
    req_enum, opt_enum, paginate,
)
from middleware import require_roles, check_member_self_ownership
from response import success

bp = Blueprint("members", __name__)

GENDERS = ("MALE", "FEMALE", "OTHER", "UNKNOWN")
RELATIONS = ("SELF", "SPOUSE", "CHILD", "OTHER_DEPENDENT")
EMPLOYMENT = ("ACTIVE", "RETIRED", "COBRA", "TERMINATED")
ENTITLEMENTS = ("NONE", "AGE", "DISABILITY", "ESRD", "ESRD_AND_AGE")


def member_view(m):
    return m


@bp.route("/cob/members", methods=["POST"])
def create_member():
    require_roles("EligibilityAnalyst")
    data = body()
    ext_id = req_str(data, "member_external_id")
    full_name = req_str(data, "full_name")
    dob = req_str(data, "date_of_birth")
    gender = req_enum(data, "gender", GENDERS)
    relation = req_enum(data, "relation_to_subscriber", RELATIONS)
    sub_id = opt_str(data, "subscriber_member_id", None)
    emp_status = req_enum(data, "employment_status", EMPLOYMENT)
    employer_size = opt_int(data, "employer_size", 0)
    custodial = opt_bool(data, "custodial_decree_on_file", False)
    entitlement = opt_enum(data, "medicare_entitlement_reason", ENTITLEMENTS, "NONE")
    esrd_onset = opt_str(data, "esrd_onset_date", None)
    if entitlement in ("ESRD", "ESRD_AND_AGE") and not esrd_onset:
        raise_err(ERR_INVALID_REQUEST, "esrd_onset_date required when entitlement includes ESRD")

    rec = base_record()
    rec.update({
        "member_external_id": ext_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "gender": gender,
        "relation_to_subscriber": relation,
        "subscriber_member_id": sub_id,
        "employment_status": emp_status,
        "employer_size": employer_size if employer_size is not None else 0,
        "custodial_decree_on_file": bool(custodial),
        "medicare_entitlement_reason": entitlement,
        "esrd_onset_date": esrd_onset,
        "other_coverage_count": 0,
        "status": "ENROLLED",
    })
    stores["members"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/members/<mid>", methods=["GET"])
def get_member(mid):
    user_id, role = require_roles(
        "PlatformAdmin", "EligibilityAnalyst", "COBAnalyst", "ClaimsExaminer",
        "RecoverySpecialist", "COBAuditor", "MemberSelf",
    )
    rec = get_or_404(stores["members"], mid, "member")
    check_member_self_ownership(user_id, role, rec["id"])
    return success(rec)


@bp.route("/cob/members", methods=["GET"])
def list_members():
    require_roles(
        "PlatformAdmin", "EligibilityAnalyst", "COBAnalyst", "ClaimsExaminer",
        "RecoverySpecialist", "COBAuditor",
    )
    items = list(stores["members"].values())
    status_filter = request.args.get("status")
    rel = request.args.get("relation_to_subscriber")
    if status_filter:
        items = [m for m in items if m.get("status") == status_filter]
    if rel:
        items = [m for m in items if m.get("relation_to_subscriber") == rel]
    return paginate(items)


@bp.route("/cob/members/<mid>/disenroll", methods=["POST"])
def disenroll_member(mid):
    require_roles("EligibilityAnalyst")
    rec = get_or_404(stores["members"], mid, "member")
    if rec.get("status") != "ENROLLED":
        raise_err(ERR_INVALID_STATE, "Member is not in a state from which disenrollment is valid")
    # Block on RECEIVED or REOPENED claims
    for c in stores["claims"].values():
        if c.get("member_id") == mid and c.get("status") in ("RECEIVED", "REOPENED"):
            raise_err(ERR_OPEN_CLAIMS_EXIST, "Member disenrollment blocked by open claims")
    rec["status"] = "DISENROLLED"
    touch(rec)
    # Cascade: pending coverages rejected, sent surveys expired
    for cov in stores["coverages"].values():
        if cov.get("member_id") == mid and cov.get("verification_status") == "PENDING_VERIFICATION":
            cov["verification_status"] = "REJECTED"
            touch(cov)
    for s in stores["surveys"].values():
        if s.get("member_id") == mid and s.get("status") == "SENT":
            s["status"] = "EXPIRED"
            touch(s)
    return success(rec)


@bp.route("/cob/members/<mid>/dependents", methods=["GET"])
def list_dependents(mid):
    require_roles("PlatformAdmin", "EligibilityAnalyst", "COBAnalyst", "ClaimsExaminer", "MemberSelf")
    get_or_404(stores["members"], mid, "member")
    items = [m for m in stores["members"].values() if m.get("subscriber_member_id") == mid]
    return paginate(items)
