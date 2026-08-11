"""Primacy determination endpoints."""

from flask import Blueprint, request

from db import stores, now_dt, parse_date
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_COVERAGE_WINDOW,
    ERR_MEMBER_DISENROLLED, ERR_STALE_VERSION, ERR_INVALID_DETERMINATION_REFERENCE,
    ERR_MSP_QUESTIONNAIRE_REQUIRED, ERR_INVALID_REQUEST,
)
from helpers import base_record, touch, get_or_404, body, req_str, opt_str, paginate
from middleware import require_roles
from response import success
from services.calculations import (
    active_config, in_scope_coverages, primacy_rule_selection,
)

bp = Blueprint("determinations", __name__)


def _get_nested_det(mid, did):
    get_or_404(stores["members"], mid, "member")
    det = stores["determinations"].get(did)
    if det is None or det.get("member_id") != mid:
        raise_err(ERR_NOT_FOUND, "determination does not exist or does not belong to member")
    return det


@bp.route("/cob/members/<mid>/primacy-determinations", methods=["POST"])
def draft_determination(mid):
    require_roles("COBAnalyst")
    member = get_or_404(stores["members"], mid, "member")
    if member.get("status") != "ENROLLED":
        raise_err(ERR_MEMBER_DISENROLLED, "Operation requires Member.status == ENROLLED")
    data = body()
    as_of = req_str(data, "as_of_service_date")
    msp_qid = opt_str(data, "msp_questionnaire_id", None)
    if "expected_member_version" not in data or data["expected_member_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "expected_member_version is required")
    expected = data["expected_member_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_member_version must be an integer")
    # Temporal: as_of_service_date on or before current clock
    if parse_date(as_of) > now_dt().date():
        raise_err(ERR_INVALID_COVERAGE_WINDOW, "future-dated service_date used in primacy determination")
    # OCC check
    if member.get("version") != expected:
        raise_err(ERR_STALE_VERSION, "expected_member_version does not match server's current version")

    rec = base_record()
    rec.update({
        "member_id": mid,
        "as_of_service_date": as_of,
        "deciding_rule": None,
        "ordered_coverage_ids": [],
        "msp_questionnaire_id": msp_qid,
        "superseded_by_id": None,
        "status": "DRAFT",
    })
    stores["determinations"][rec["id"]] = rec
    touch(member)
    return success(rec, status=201)


@bp.route("/cob/members/<mid>/primacy-determinations", methods=["GET"])
def list_determinations(mid):
    require_roles("PlatformAdmin", "COBAnalyst", "ClaimsExaminer", "RecoverySpecialist", "MemberSelf")
    get_or_404(stores["members"], mid, "member")
    items = [d for d in stores["determinations"].values() if d.get("member_id") == mid]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d.get("status") == status]
    return paginate(items)


@bp.route("/cob/members/<mid>/primacy-determinations/<did>", methods=["GET"])
def get_determination(mid, did):
    require_roles("PlatformAdmin", "COBAnalyst", "ClaimsExaminer", "RecoverySpecialist", "MemberSelf")
    det = _get_nested_det(mid, did)
    return success(det)


@bp.route("/cob/members/<mid>/primacy-determinations/<did>/finalize", methods=["POST"])
def finalize_determination(mid, did):
    require_roles("COBAnalyst")
    det = _get_nested_det(mid, did)
    member = stores["members"][mid]
    if det.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Determination is not in DRAFT")

    in_scope = in_scope_coverages(mid, det["as_of_service_date"])
    has_medicare = any(c.get("coverage_kind", "").startswith("MEDICARE_") for c in in_scope)

    # MSP compliance (priority 8 per validations)
    questionnaire = None
    if has_medicare:
        qid = det.get("msp_questionnaire_id")
        if not qid:
            raise_err(ERR_MSP_QUESTIONNAIRE_REQUIRED, "msp_questionnaire_id required for MEDICARE_* coverage")
        questionnaire = stores["questionnaires"].get(qid)
        if questionnaire is None or questionnaire.get("member_id") != mid or questionnaire.get("status") != "ADJUDICATED":
            raise_err(ERR_MSP_QUESTIONNAIRE_REQUIRED, "referenced questionnaire must be ADJUDICATED for this member")
    elif det.get("msp_questionnaire_id"):
        q = stores["questionnaires"].get(det["msp_questionnaire_id"])
        if q is None or q.get("member_id") != mid or q.get("status") != "ADJUDICATED":
            raise_err(ERR_INVALID_DETERMINATION_REFERENCE, "referenced questionnaire invalid")

    config = active_config()
    rule, ordered = primacy_rule_selection(member, in_scope, questionnaire, config)
    det["deciding_rule"] = rule
    det["ordered_coverage_ids"] = [c["id"] for c in ordered]
    det["status"] = "FINALIZED"
    touch(det)
    touch(member)

    # Supersede any prior FINALIZED determination for the same member + date
    for other in list(stores["determinations"].values()):
        if (other["id"] != det["id"] and other.get("member_id") == mid
                and other.get("status") == "FINALIZED"
                and other.get("as_of_service_date") == det["as_of_service_date"]):
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = det["id"]
            touch(other)
            # Auto-create adjustments for claims using the old determination
            for claim in stores["claims"].values():
                if (claim.get("member_id") == mid
                        and claim.get("service_date") == other["as_of_service_date"]
                        and claim.get("primacy_determination_id") == other["id"]):
                    adj = base_record()
                    adj.update({
                        "claim_id": claim["id"],
                        "cause": "PRIMACY_DETERMINATION_SUPERSEDED",
                        "triggering_determination_id": det["id"],
                        "pre_paid_cents": None,
                        "post_paid_cents": None,
                        "overpayment_cents": None,
                        "underpayment_cents": None,
                        "status": "DRAFT",
                    })
                    stores["adjustments"][adj["id"]] = adj

    return success(det)


# ---- Top-level reverse-lookup endpoints ----

@bp.route("/cob/primacy-determinations/<did>", methods=["GET"])
def get_determination_top(did):
    require_roles("PlatformAdmin", "COBAnalyst", "ClaimsExaminer", "RecoverySpecialist", "MemberSelf")
    det = get_or_404(stores["determinations"], did, "determination")
    return success(det)


@bp.route("/cob/primacy-determinations", methods=["GET"])
def list_determinations_top():
    require_roles("PlatformAdmin", "COBAnalyst", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    items = list(stores["determinations"].values())
    status = request.args.get("status")
    msp_qid = request.args.get("msp_questionnaire_id")
    superseded_by = request.args.get("superseded_by_id")
    member_id = request.args.get("member_id")
    if status:
        items = [d for d in items if d.get("status") == status]
    if msp_qid:
        items = [d for d in items if d.get("msp_questionnaire_id") == msp_qid]
    if superseded_by:
        items = [d for d in items if d.get("superseded_by_id") == superseded_by]
    if member_id:
        items = [d for d in items if d.get("member_id") == member_id]
    return paginate(items)
