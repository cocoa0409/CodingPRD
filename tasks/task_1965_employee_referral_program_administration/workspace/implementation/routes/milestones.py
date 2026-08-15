"""Bonus milestone reads, approval (withholding lock + annual cap), forfeit."""

from flask import Blueprint, request, g

from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
                    ERR_ANNUAL_CAP_EXCEEDED, ERR_TAX_PROFILE_NOT_VERIFIED)
from middleware import require_role
import services as svc
from services import touch
from util import respond_object, respond_list, parse_pagination, paginate
from views import milestone_view

bp = Blueprint("milestones", __name__)

READ_ROLES = ("PlatformAdmin", "TalentAdmin", "Recruiter", "PayrollProcessor",
              "ComplianceOfficer")


def _get_milestone(milestone_id):
    m = store.milestones.get(milestone_id)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Milestone not found")
    return m


@bp.get("/erp/milestones")
def list_milestones():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.milestones.values())
    for param in ("referral_id", "payroll_batch_id", "status", "kind"):
        value = request.args.get(param)
        if value is not None:
            items = [m for m in items if m[param] == value]
    page, total = paginate(items, limit, offset)
    return respond_list([milestone_view(m) for m in page], total, limit, offset)


@bp.get("/erp/milestones/<milestone_id>")
def get_milestone(milestone_id):
    require_role(*READ_ROLES)
    return respond_object(milestone_view(_get_milestone(milestone_id)))


@bp.post("/erp/milestones/<milestone_id>/approve")
def approve_milestone(milestone_id):
    require_role("PayrollProcessor")
    m = _get_milestone(milestone_id)
    if m["status"] in svc.MILESTONE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Milestone is in terminal state %s" % m["status"])
    if m["status"] != "EARNED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an EARNED milestone can be approved (currently %s)" % m["status"])
    referral = store.referrals[m["referral_id"]]
    policy = store.policies[referral["policy_version_id"]]
    # Gate 1: annual cap (committed lens) against the pinned policy.
    _provisional, committed = svc.annual_accumulators(referral["referrer_id"])
    if committed + m["amount_cents"] > policy["annual_cap_cents"]:
        raise ApiError(ERR_ANNUAL_CAP_EXCEEDED, 422,
                       "Approval would exceed the referrer's annual cap")
    # Gate 2: the referrer's tax profile must exist and be VERIFIED.
    profile = store.tax_profiles.get(referral["referrer_id"])
    if profile is None or profile["status"] != "VERIFIED":
        raise ApiError(ERR_TAX_PROFILE_NOT_VERIFIED, 422,
                       "Referrer's tax profile is missing or not VERIFIED")
    # Withholding computed and locked at this instant.
    withholding = svc.compute_withholding(m["amount_cents"], profile)
    m["withholding_cents"] = withholding
    m["net_cents"] = m["amount_cents"] - withholding
    m["approved_by_user_id"] = g.user_id
    m["status"] = "APPROVED"
    touch(m)
    return respond_object(milestone_view(m))


@bp.post("/erp/milestones/<milestone_id>/forfeit")
def forfeit_milestone(milestone_id):
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: reason")
    require_role("PayrollProcessor", "ComplianceOfficer")
    m = _get_milestone(milestone_id)
    if m["status"] in svc.MILESTONE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Milestone is in terminal state %s" % m["status"])
    if m["status"] not in ("EARNED", "APPROVED"):
        # PENDING or BATCHED: the manual forfeit action is not defined.
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an EARNED or APPROVED milestone can be manually forfeited (currently %s)"
                       % m["status"])
    svc.forfeit_milestone(m)
    return respond_object(milestone_view(m))
