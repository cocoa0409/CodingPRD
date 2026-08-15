"""TrustAccount CRUD + lifecycle transitions + on-demand compliance check."""

from flask import Blueprint, request

import db
import serialize
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_TRUST_NOT_ACTIVE, ERR_UNRESOLVED_COMPLIANCE_REVIEWS,
                    ERR_DOCUMENT_NOT_APPROVED, ERR_SHARE_SUM_INVALID)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import trust_json
from services import workflow, calc
from services.workflow import find_trust_path
from validation import get_body, validate, parse_pagination

bp = Blueprint("trusts", __name__)

TRUST_TYPES = {"REVOCABLE", "IRREVOCABLE", "TESTAMENTARY", "CHARITABLE"}
DISTRIBUTION_STANDARDS = {"HEMS", "SUPPORT", "DISCRETIONARY"}
READ_ROLES = {"TrustOfficer", "TrustExecutive", "InvestmentManager",
              "TrustOperationsOfficer", "TaxSpecialist"}


@bp.route("/trusts", methods=["POST"])
def create_trust():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_name", "str", True),
        ("trust_type", "str", True, TRUST_TYPES),
        ("grantor_name", "str", True),
        ("governing_state", "str", True),
        ("ein", "str", True),
        ("fiscal_year_end_month", "int", True),
        ("distribution_standard", "str", True, DISTRIBUTION_STANDARDS),
    ])
    if not (1 <= v["fiscal_year_end_month"] <= 12):
        raise ApiError(ERR_VALIDATION, 400, "fiscal_year_end_month must be 1..12")
    require_role(role, {"TrustOfficer"})
    t = workflow.new_entity()
    t.update({
        "trust_name": v["trust_name"],
        "trust_type": v["trust_type"],
        "grantor_name": v["grantor_name"],
        "governing_state": v["governing_state"],
        "ein": v["ein"],
        "fiscal_year_end_month": v["fiscal_year_end_month"],
        "distribution_standard": v["distribution_standard"],
        "status": "DRAFT",
        "accepted_at": None,
    })
    db.trusts[t["id"]] = t
    return ok(trust_json(t), status=201)


@bp.route("/trusts", methods=["GET"])
def list_trusts():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    trust_type = request.args.get("trust_type")
    if trust_type is not None:
        filters.append(("trust_type", trust_type))
    items, total = workflow.list_page(db.trusts, filters, trust_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/<tid>", methods=["GET"])
def get_trust(tid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    t = find_trust_path(tid)
    return ok(trust_json(t))


@bp.route("/trusts/<tid>/submit-for-acceptance", methods=["POST"])
def submit_for_acceptance(tid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    t = find_trust_path(tid)
    if t["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Trust must be DRAFT to submit for acceptance")
    t["status"] = "UNDER_ACCEPTANCE_REVIEW"
    workflow.bump_trust(t)
    return ok(trust_json(t))


@bp.route("/trusts/<tid>/accept", methods=["POST"])
def accept_trust(tid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustExecutive"})
    t = find_trust_path(tid)
    if t["status"] != "UNDER_ACCEPTANCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Trust must be UNDER_ACCEPTANCE_REVIEW to accept")
    # [9] an APPROVED TrustDocument must exist
    approved = any(d["trust_id"] == tid and d["status"] == "APPROVED"
                   for d in db.documents.values())
    if not approved:
        raise ApiError(ERR_DOCUMENT_NOT_APPROVED, 409,
                       "No APPROVED TrustDocument for this trust")
    # [10] every class with >=1 ACTIVE member must sum to exactly 10000 bps
    for cls in ("INCOME", "REMAINDER"):
        members = [b for b in db.beneficiaries.values()
                   if b["trust_id"] == tid and b["beneficiary_class"] == cls
                   and b["status"] == "ACTIVE"]
        if members and sum(b["share_bps"] for b in members) != 10000:
            raise ApiError(ERR_SHARE_SUM_INVALID, 422,
                           "ACTIVE %s class share_bps must sum to 10000" % cls)
    t["status"] = "ACTIVE"
    t["accepted_at"] = workflow.now_stamp()
    workflow.bump_trust(t)
    return ok(trust_json(t))


@bp.route("/trusts/<tid>/decline-acceptance", methods=["POST"])
def decline_acceptance(tid):
    _, role = authenticate()
    data = get_body()
    validate(data, [("reason", "str", True)])
    require_role(role, {"TrustExecutive"})
    t = find_trust_path(tid)
    if t["status"] != "UNDER_ACCEPTANCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Trust must be UNDER_ACCEPTANCE_REVIEW to decline")
    t["status"] = "ACCEPTANCE_DECLINED"
    workflow.bump_trust(t)
    return ok(trust_json(t))


@bp.route("/trusts/<tid>/suspend", methods=["POST"])
def suspend_trust(tid):
    _, role = authenticate()
    data = get_body()
    validate(data, [("reason", "str", True)])
    require_role(role, {"TrustExecutive"})
    t = find_trust_path(tid)
    if t["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Trust must be ACTIVE to suspend")
    t["status"] = "SUSPENDED"
    workflow.bump_trust(t)
    return ok(trust_json(t))


@bp.route("/trusts/<tid>/reinstate", methods=["POST"])
def reinstate_trust(tid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustExecutive"})
    t = find_trust_path(tid)
    if t["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Trust must be SUSPENDED to reinstate")
    unresolved = any(r["trust_id"] == tid and r["status"] in
                     ("OPEN", "REMEDIATION_PLANNED", "ESCALATED")
                     for r in db.reviews.values())
    if unresolved:
        raise ApiError(ERR_UNRESOLVED_COMPLIANCE_REVIEWS, 409,
                       "Trust has unresolved compliance reviews")
    t["status"] = "ACTIVE"
    workflow.bump_trust(t)
    return ok(trust_json(t))


@bp.route("/trusts/<tid>/terminate", methods=["POST"])
def terminate_trust(tid):
    user_id, role = authenticate()
    data = get_body()
    v = validate(data, [("reason", "str", True)])
    require_role(role, {"TrustOfficer", "TrustExecutive"})
    t = find_trust_path(tid)
    if t["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Trust must be ACTIVE to terminate")
    # Cascade 1+2: cancel non-terminal distribution requests; reservations are
    # derived from request status, so release is automatic on CANCELLED.
    for r in db.distribution_requests.values():
        if r["trust_id"] == tid and r["status"] in serialize.PENDING_STATES:
            r["status"] = "CANCELLED"
            r["cancelled_reason"] = "TRUST_TERMINATING"
            workflow.touch(r)
    # Cascade 3: create the TerminationCase in INITIATED
    case = workflow.new_entity()
    case.update({
        "trust_id": tid,
        "status": "INITIATED",
        "reason": v["reason"],
        "initiated_by_user_id": user_id,
        "reserve_taxes_cents": None,
        "reserve_fees_cents": None,
        "distributable_income_cents": None,
        "distributable_principal_cents": None,
        "distribution_lines": None,
        "approved_by_user_id": None,
        "distributed_at": None,
    })
    db.termination_cases[case["id"]] = case
    t["status"] = "TERMINATING"
    workflow.bump_trust(t)
    return ok(trust_json(t))


@bp.route("/trusts/<tid>/run-compliance-check", methods=["POST"])
def run_compliance_check(tid):
    _, role = authenticate()
    get_body()
    require_role(role, {"InvestmentManager", "TrustOfficer"})
    t = find_trust_path(tid)
    count, ids = calc.run_drift_check(t)
    return ok({"opened_review_count": count, "opened_review_ids": ids})


# guard against flask treating action paths as <tid> for unknown methods is
# unnecessary; declared routes take precedence by specificity.
