"""OwnershipDispute endpoints + SLA checkpoint."""
from datetime import date

from flask import Blueprint, request

from db import store, logical_today
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  opt_string, req_enum, find_or_404, paginate, stamp_new, touch)
from services import calc

bp = Blueprint("disputes", __name__)

REP = ("SalesRep",)
MGR = ("RevOpsManager",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")
OPEN_STATUSES = ("FILED", "UNDER_REVIEW", "ESCALATED")


@bp.route("/sales-planning/disputes", methods=["POST"])
def create_dispute():
    ctx = get_user_context()
    require_role(ctx, REP)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "account_id", "claimant_territory_id", "reason"})
    require_fields(body, ["plan_year_id", "account_id", "claimant_territory_id", "reason"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    account = find_or_404(store.accounts, body["account_id"], "account")
    claimant = find_or_404(store.territories, body["claimant_territory_id"], "claimant territory")
    reason = req_string(body, "reason")

    # Tier 4: plan gate
    if plan["status"] not in ("COMMUNICATED", "LOCKED"):
        raise ApiError("ERR_PLAN_NOT_COMMUNICATED",
                       "Disputes require plan status COMMUNICATED or LOCKED", 409)
    if claimant["status"] != "ACTIVE":
        raise ApiError("ERR_TERRITORY_NOT_ACTIVE", "Claimant territory is not ACTIVE", 409)

    # Tier 5: cross-plan
    if account["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "account_id belongs to a different plan year", 409)
    if claimant["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "claimant_territory_id belongs to a different plan year", 409)

    # Tier 7 guards
    if account["assigned_territory_id"] == claimant["id"]:
        raise ApiError("ERR_CLAIMANT_TERRITORY_INVALID",
                       "Claimant territory equals the account's current assigned territory", 422)
    member = any(a["rep_id"] == ctx.user_id and a["territory_id"] == claimant["id"]
                 and a["status"] == "ACTIVE" for a in store.rep_assignments.values())
    if not member:
        raise ApiError("ERR_NOT_TERRITORY_MEMBER",
                       "Filer holds no ACTIVE assignment on the claimant territory", 409)
    open_disputes = [d for d in store.disputes.values()
                     if d["account_id"] == account["id"] and d["status"] in OPEN_STATUSES]
    if open_disputes:
        raise ApiError("ERR_DISPUTE_ALREADY_OPEN",
                       "Account already has an open dispute", 409)

    d = stamp_new({
        "plan_year_id": plan["id"],
        "account_id": account["id"],
        "claimant_territory_id": claimant["id"],
        "filed_by_rep_id": ctx.user_id,
        "reason": reason,
        "filed_date": logical_today().isoformat(),
        "status": "FILED",
    })
    store.disputes[d["id"]] = d
    return success_object(calc.ser_dispute(d), status=201)


@bp.route("/sales-planning/disputes", methods=["GET"])
def list_disputes():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.disputes.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [d for d in items if d["plan_year_id"] == v]
    if (v := request.args.get("account_id")) is not None:
        items = [d for d in items if d["account_id"] == v]
    if (v := request.args.get("claimant_territory_id")) is not None:
        items = [d for d in items if d["claimant_territory_id"] == v]
    if (v := request.args.get("filed_by_rep_id")) is not None:
        items = [d for d in items if d["filed_by_rep_id"] == v]
    if (v := request.args.get("status")) is not None:
        items = [d for d in items if d["status"] == v]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_dispute(d) for d in page], limit, offset, total)


@bp.route("/sales-planning/disputes/<did>", methods=["GET"])
def get_dispute(did):
    ctx = get_user_context()
    require_role(ctx, ALL)
    d = find_or_404(store.disputes, did, "dispute")
    return success_object(calc.ser_dispute(d))


@bp.route("/sales-planning/disputes/<did>/start-review", methods=["POST"])
def start_review(did):
    ctx = get_user_context()
    require_role(ctx, MGR)
    d = find_or_404(store.disputes, did, "dispute")
    get_body()
    if d["status"] not in ("FILED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot start review of dispute in status {d['status']}", 409)
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success_object(calc.ser_dispute(d))


@bp.route("/sales-planning/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    ctx = get_user_context()
    require_role(ctx, MGR)
    d = find_or_404(store.disputes, did, "dispute")
    body = get_body()
    reject_unknown_fields(body, {"resolution", "note"})
    require_fields(body, ["resolution"])
    resolution = req_enum(body, "resolution", ("UPHELD", "OVERRULED"))
    if d["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot resolve dispute in status {d['status']}", 409)
    if resolution == "UPHELD":
        account = find_or_404(store.accounts, d["account_id"], "account")
        account["assigned_territory_id"] = d["claimant_territory_id"]
        account["assignment_source"] = "DISPUTE_RESOLUTION"
        account["assignment_rule_id"] = None
        touch(account)
        d["status"] = "RESOLVED_UPHELD"
    else:
        d["status"] = "RESOLVED_OVERRULED"
    touch(d)
    return success_object(calc.ser_dispute(d))


@bp.route("/sales-planning/disputes/<did>/withdraw", methods=["POST"])
def withdraw_dispute(did):
    ctx = get_user_context()
    require_role(ctx, REP)
    d = find_or_404(store.disputes, did, "dispute")
    get_body()
    # Ownership (tier 2)
    if ctx.user_id != d["filed_by_rep_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Only the filer may withdraw this dispute", 403)
    if d["status"] not in ("FILED", "UNDER_REVIEW", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot withdraw dispute in status {d['status']}", 409)
    d["status"] = "WITHDRAWN"
    touch(d)
    return success_object(calc.ser_dispute(d))


@bp.route("/sales-planning/plan-years/<pid>/process-dispute-slas", methods=["POST"])
def process_slas(pid):
    ctx = get_user_context()
    require_role(ctx, MGR)
    get_body()
    plan = find_or_404(store.plan_years, pid, "plan year")
    return success_object(calc.process_dispute_slas(plan))
