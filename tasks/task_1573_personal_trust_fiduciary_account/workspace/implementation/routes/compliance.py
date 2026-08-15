"""ComplianceReview workflow: plan remediation, escalate, resolve."""

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_INVALID_STATE, ERR_DRIFT_STILL_BREACHED)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import review_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("compliance", __name__)

READ_ROLES = {"TrustOfficer", "TrustExecutive", "InvestmentManager"}


@bp.route("/trusts/compliance-reviews", methods=["GET"])
def list_reviews():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "investment_policy_statement_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.reviews, filters, review_json,
                                      limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/compliance-reviews/<rid>", methods=["GET"])
def get_review(rid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    r = find_or_404(db.reviews, rid, "ComplianceReview")
    return ok(review_json(r))


@bp.route("/trusts/compliance-reviews/<rid>/plan-remediation", methods=["POST"])
def plan_remediation(rid):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [("remediation_note", "str", True)])
    require_role(role, {"InvestmentManager"})
    r = find_or_404(db.reviews, rid, "ComplianceReview")
    if r["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Review must be OPEN to plan remediation")
    r["status"] = "REMEDIATION_PLANNED"
    r["remediation_note"] = v["remediation_note"]
    workflow.touch(r)
    return ok(review_json(r))


@bp.route("/trusts/compliance-reviews/<rid>/escalate", methods=["POST"])
def escalate(rid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustExecutive"})
    r = find_or_404(db.reviews, rid, "ComplianceReview")
    if r["status"] not in ("OPEN", "REMEDIATION_PLANNED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Review must be OPEN or REMEDIATION_PLANNED to escalate")
    r["status"] = "ESCALATED"
    workflow.touch(r)
    return ok(review_json(r))


@bp.route("/trusts/compliance-reviews/<rid>/resolve", methods=["POST"])
def resolve(rid):
    _, role = authenticate()
    get_body()
    require_role(role, {"InvestmentManager"})
    r = find_or_404(db.reviews, rid, "ComplianceReview")
    if r["status"] not in ("OPEN", "REMEDIATION_PLANNED", "ESCALATED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Review cannot be resolved from its current state")
    # drift must be cured: current unrounded weight back within band inclusive
    policy = db.policies.get(r["investment_policy_statement_id"])
    trust = db.trusts.get(r["trust_id"])
    cured = False
    if policy is not None and trust is not None:
        raw = calc.current_weight(trust["id"], r["asset_class"], policy)
        if raw is not None:
            target, band = calc._targets(policy, r["asset_class"])
            cured = calc.within_band(raw, target, band)
    if not cured:
        raise ApiError(ERR_DRIFT_STILL_BREACHED, 409,
                       "Current class weight is still outside the IPS band")
    r["status"] = "RESOLVED"
    r["resolved_at"] = workflow.now_stamp()
    workflow.touch(r)
    return ok(review_json(r))
