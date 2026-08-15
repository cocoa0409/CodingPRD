"""BottomUpSubmission endpoints."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  opt_string, req_int, find_or_404, paginate, stamp_new, touch)
from services import calc

bp = Blueprint("submissions", __name__)

REP = ("SalesRep",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


@bp.route("/sales-planning/submissions", methods=["POST"])
def create_submission():
    ctx = get_user_context()
    require_role(ctx, REP)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "territory_id", "proposed_quota_cents",
                                 "rationale"})
    require_fields(body, ["plan_year_id", "territory_id", "proposed_quota_cents"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    territory = find_or_404(store.territories, body["territory_id"], "territory")
    proposed = req_int(body, "proposed_quota_cents")
    rationale = opt_string(body, "rationale")

    if plan["status"] != "OPEN":
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                       "Submission create requires plan status OPEN", 409)
    if territory["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "territory_id belongs to a different plan year", 409)

    # Membership: acting rep must hold an ACTIVE assignment on the territory
    member = any(a["rep_id"] == ctx.user_id and a["territory_id"] == territory["id"]
                 and a["status"] == "ACTIVE"
                 for a in store.rep_assignments.values())
    if not member:
        raise ApiError("ERR_NOT_TERRITORY_MEMBER",
                       "Acting rep holds no ACTIVE assignment on this territory", 409)

    dup = [s for s in store.submissions.values()
           if s["territory_id"] == territory["id"] and s["status"] == "SUBMITTED"]
    if dup:
        raise ApiError("ERR_DUPLICATE_SUBMISSION",
                       "Territory already has a SUBMITTED submission", 409)

    if proposed <= 0:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", "proposed_quota_cents must be > 0", 422)

    sub = stamp_new({
        "plan_year_id": plan["id"],
        "territory_id": territory["id"],
        "submitted_by_rep_id": ctx.user_id,
        "proposed_quota_cents": proposed,
        "rationale": rationale,
        "status": "SUBMITTED",
    })
    store.submissions[sub["id"]] = sub
    return success_object(calc.ser_submission(sub), status=201)


@bp.route("/sales-planning/submissions", methods=["GET"])
def list_submissions():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.submissions.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [s for s in items if s["plan_year_id"] == v]
    if (v := request.args.get("territory_id")) is not None:
        items = [s for s in items if s["territory_id"] == v]
    if (v := request.args.get("submitted_by_rep_id")) is not None:
        items = [s for s in items if s["submitted_by_rep_id"] == v]
    if (v := request.args.get("status")) is not None:
        items = [s for s in items if s["status"] == v]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_submission(s) for s in page], limit, offset, total)


@bp.route("/sales-planning/submissions/<sid>", methods=["GET"])
def get_submission(sid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    s = find_or_404(store.submissions, sid, "submission")
    return success_object(calc.ser_submission(s))


@bp.route("/sales-planning/submissions/<sid>/withdraw", methods=["POST"])
def withdraw_submission(sid):
    ctx = get_user_context()
    require_role(ctx, REP)
    s = find_or_404(store.submissions, sid, "submission")
    # Ownership (tier 2)
    if ctx.user_id != s["submitted_by_rep_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Only the submitter may withdraw this submission", 403)
    plan = find_or_404(store.plan_years, s["plan_year_id"], "plan year")
    if plan["status"] != "OPEN":
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                       "Submission withdraw requires plan status OPEN", 409)
    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot withdraw submission in status {s['status']}", 409)
    s["status"] = "WITHDRAWN"
    touch(s)
    return success_object(calc.ser_submission(s))
