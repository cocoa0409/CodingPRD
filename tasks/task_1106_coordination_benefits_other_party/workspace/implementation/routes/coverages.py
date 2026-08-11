"""Coverage endpoints."""

from flask import Blueprint, request

from db import stores, now_dt, parse_date
from errors import (
    raise_err, ERR_MEMBER_DISENROLLED, ERR_INVALID_STATE,
    ERR_INVALID_COVERAGE_WINDOW, ERR_DUPLICATE_OUR_PLAN, ERR_NOT_FOUND,
)
from helpers import (
    base_record, touch, get_or_404, body, req_str, opt_str, req_enum, opt_enum, paginate,
)
from middleware import require_roles, check_member_self_ownership
from response import success

bp = Blueprint("coverages", __name__)

COVERAGE_KINDS = (
    "OUR_PLAN", "GROUP_HEALTH", "MEDICARE_PART_A", "MEDICARE_PART_B",
    "MEDICARE_ADVANTAGE", "MEDICAID", "TRICARE", "INDIVIDUAL",
)
SUB_REL = ("SELF", "SPOUSE", "PARENT", "OTHER")
GENDERS = ("MALE", "FEMALE", "OTHER", "UNKNOWN")
VERIF_SOURCES = ("MEMBER_SURVEY", "DATA_MATCH_CMS", "CLAIM_INDICATION", "ELIGIBILITY_MATCH")


def _recompute_other_coverage_count(member_id):
    m = stores["members"].get(member_id)
    if m is None:
        return
    count = 0
    for c in stores["coverages"].values():
        if c.get("member_id") == member_id and c.get("verification_status") == "VERIFIED" and c.get("coverage_kind") != "OUR_PLAN":
            count += 1
    m["other_coverage_count"] = count


def _linked_lead(member_id, source):
    for lead in stores["leads"].values():
        if lead.get("member_id") == member_id and lead.get("source") == source and lead.get("disposition") == "RECEIVED":
            return lead
    return None


@bp.route("/cob/members/<mid>/coverages", methods=["POST"])
def create_coverage(mid):
    require_roles("COBAnalyst", "EligibilityAnalyst")
    member = get_or_404(stores["members"], mid, "member")
    if member.get("status") != "ENROLLED":
        raise_err(ERR_MEMBER_DISENROLLED, "Operation requires Member.status == ENROLLED")
    data = body()
    payer_id = req_str(data, "payer_id")
    plan_name = req_str(data, "plan_name")
    kind = req_enum(data, "coverage_kind", COVERAGE_KINDS)
    sub_rel = req_enum(data, "subscriber_relationship", SUB_REL)
    ph_dob = req_str(data, "policy_holder_dob")
    ph_gender = opt_enum(data, "policy_holder_gender", GENDERS, "UNKNOWN")
    eff_from = req_str(data, "effective_from")
    eff_to = opt_str(data, "effective_to", None)
    verif_source = req_enum(data, "verification_source", VERIF_SOURCES)

    if eff_to is not None:
        if parse_date(eff_from) >= parse_date(eff_to):
            raise_err(ERR_INVALID_COVERAGE_WINDOW, "Coverage.effective_from must be before effective_to")

    rec = base_record()
    rec.update({
        "member_id": mid,
        "payer_id": payer_id,
        "plan_name": plan_name,
        "coverage_kind": kind,
        "subscriber_relationship": sub_rel,
        "policy_holder_dob": ph_dob,
        "policy_holder_gender": ph_gender,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "verification_source": verif_source,
        "verification_status": "PENDING_VERIFICATION",
        "is_ours": kind == "OUR_PLAN",
    })
    stores["coverages"][rec["id"]] = rec
    # Link a matching RECEIVED lead
    lead = _linked_lead(mid, verif_source)
    if lead is not None:
        rec["linked_lead_id"] = lead["id"]
    return success(rec, status=201)


@bp.route("/cob/members/<mid>/coverages", methods=["GET"])
def list_coverages(mid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "ClaimsExaminer", "RecoverySpecialist", "MemberSelf")
    get_or_404(stores["members"], mid, "member")
    items = [c for c in stores["coverages"].values() if c.get("member_id") == mid]
    vs = request.args.get("verification_status")
    kind = request.args.get("coverage_kind")
    if vs:
        items = [c for c in items if c.get("verification_status") == vs]
    if kind:
        items = [c for c in items if c.get("coverage_kind") == kind]
    return paginate(items)


def _get_nested_coverage(mid, cid):
    get_or_404(stores["members"], mid, "member")
    cov = stores["coverages"].get(cid)
    if cov is None or cov.get("member_id") != mid:
        raise_err(ERR_NOT_FOUND, "coverage does not exist or does not belong to member")
    return cov


@bp.route("/cob/members/<mid>/coverages/<cid>", methods=["GET"])
def get_coverage(mid, cid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "ClaimsExaminer", "RecoverySpecialist", "MemberSelf")
    cov = _get_nested_coverage(mid, cid)
    return success(cov)


@bp.route("/cob/members/<mid>/coverages/<cid>/verify", methods=["POST"])
def verify_coverage(mid, cid):
    require_roles("COBAnalyst")
    cov = _get_nested_coverage(mid, cid)
    member = stores["members"][mid]
    if member.get("status") != "ENROLLED":
        raise_err(ERR_MEMBER_DISENROLLED, "Operation requires Member.status == ENROLLED")
    if cov.get("verification_status") != "PENDING_VERIFICATION":
        raise_err(ERR_INVALID_STATE, "Coverage is not in PENDING_VERIFICATION")
    if cov.get("effective_to") is not None:
        if parse_date(cov["effective_from"]) >= parse_date(cov["effective_to"]):
            raise_err(ERR_INVALID_COVERAGE_WINDOW, "effective_from must be < effective_to")
    if cov.get("coverage_kind") == "OUR_PLAN":
        for other in stores["coverages"].values():
            if (other["id"] != cid and other.get("member_id") == mid
                    and other.get("coverage_kind") == "OUR_PLAN"
                    and other.get("verification_status") == "VERIFIED"):
                raise_err(ERR_DUPLICATE_OUR_PLAN, "Another VERIFIED OUR_PLAN coverage already exists for this member")
    cov["verification_status"] = "VERIFIED"
    touch(cov)
    _recompute_other_coverage_count(mid)
    lead = _linked_lead(mid, cov.get("verification_source"))
    if lead is not None:
        lead["disposition"] = "VERIFIED_COVERAGE"
        touch(lead)
    touch(member)
    return success(cov)


@bp.route("/cob/members/<mid>/coverages/<cid>/reject", methods=["POST"])
def reject_coverage(mid, cid):
    require_roles("COBAnalyst")
    cov = _get_nested_coverage(mid, cid)
    if cov.get("verification_status") != "PENDING_VERIFICATION":
        raise_err(ERR_INVALID_STATE, "Coverage is not in PENDING_VERIFICATION")
    cov["verification_status"] = "REJECTED"
    touch(cov)
    _recompute_other_coverage_count(mid)
    lead = _linked_lead(mid, cov.get("verification_source"))
    if lead is not None:
        lead["disposition"] = "REJECTED_NO_COVERAGE"
        touch(lead)
    return success(cov)
