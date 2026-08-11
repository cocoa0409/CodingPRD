"""Ramp milestone endpoints (PRD 3.8)."""

from flask import Blueprint, request

import domain as D
from db import store, bump
from errors import (
    ApiError, ERR_MILESTONE_NOT_FOUND, ERR_MILESTONE_NOT_PENDING,
    ERR_MILESTONE_NOT_REPORTED, ERR_REPORTING_WINDOW_CLOSED,
    ERR_GUARANTEE_NOT_ACTIVE,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("milestones", __name__)


def _get_milestone(mid):
    milestone = store.milestones.get(mid)
    if milestone is None:
        raise ApiError(ERR_MILESTONE_NOT_FOUND, 404, "RampMilestone not found")
    return milestone


@bp.route("/onboarding/ramp-milestones/<mid>", methods=["GET"])
def get_milestone(mid):
    get_context()
    return success_object(D.serialize_milestone(_get_milestone(mid)))


@bp.route("/onboarding/ramp-milestones", methods=["GET"])
def list_milestones():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    status = request.args.get("status")
    month_offset = request.args.get("month_offset")
    records = sorted(store.milestones.values(),
                     key=lambda r: (r["month_offset"], r["_seq"]))
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if month_offset is not None:
        try:
            offset_val = int(month_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "month_offset filter must be an integer")
        records = [r for r in records if r["month_offset"] == offset_val]
    return paginate([D.serialize_milestone(r) for r in records], request.args)


@bp.route("/onboarding/ramp-milestones/<mid>/report", methods=["POST"])
def report_milestone(mid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    milestone = _get_milestone(mid)
    body = D.get_body()
    actual_wrvu = D.non_negative(D.req_int(body, "actual_wrvu"), "actual_wrvu")
    collections = D.non_negative(D.req_int(body, "collections_cents"), "collections_cents")
    if milestone["status"] != "PENDING":
        raise ApiError(ERR_MILESTONE_NOT_PENDING, 409,
                       "Only a PENDING milestone can be reported")
    guarantee = D.guarantee_of_case(milestone["onboarding_case_id"])
    deadline = D.reporting_deadline(guarantee["start_month"], milestone["month_offset"])
    if D.clock_date() > deadline:
        raise ApiError(ERR_REPORTING_WINDOW_CLOSED, 422,
                       "The reporting window has closed for this milestone")
    milestone["actual_wrvu"] = actual_wrvu
    milestone["collections_cents"] = collections
    milestone["status"] = "REPORTED"
    bump(milestone)
    return success_object(D.serialize_milestone(milestone))


@bp.route("/onboarding/ramp-milestones/<mid>/attest", methods=["POST"])
def attest_milestone(mid):
    _uid, role = get_context()
    require_role(role, ["FinanceAnalyst"])
    milestone = _get_milestone(mid)
    if milestone["status"] != "REPORTED":
        raise ApiError(ERR_MILESTONE_NOT_REPORTED, 409,
                       "Only a REPORTED milestone can be attested")
    guarantee = D.guarantee_of_case(milestone["onboarding_case_id"])
    if guarantee is None or guarantee["status"] != "ACTIVE":
        raise ApiError(ERR_GUARANTEE_NOT_ACTIVE, 409,
                       "The case's income guarantee must be ACTIVE to attest")
    milestone["attained"] = milestone["actual_wrvu"] >= milestone["target_wrvu"]
    milestone["status"] = "ATTESTED"
    bump(milestone)
    bump(guarantee)
    case = store.cases.get(milestone["onboarding_case_id"])
    if case is not None:
        D.recompute_case_counts(case)
        bump(case)
    return success_object(D.serialize_milestone(milestone))
