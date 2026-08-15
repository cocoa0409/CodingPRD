"""TerritoryChangeRequest endpoints."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store, logical_today
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  opt_string, req_int, parse_date, find_or_404, paginate,
                  stamp_new, touch)
from services import calc

bp = Blueprint("change_requests", __name__)

ANALYST = ("SalesOpsAnalyst",)
MGR = ("RevOpsManager",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")
NON_TERMINAL = ("PENDING", "APPROVED")


@bp.route("/sales-planning/change-requests", methods=["POST"])
def create_change_request():
    ctx = get_user_context()
    require_role(ctx, ANALYST)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "account_id", "from_territory_id",
                                 "to_territory_id", "effective_date", "reason"})
    require_fields(body, ["plan_year_id", "account_id", "from_territory_id",
                          "to_territory_id", "effective_date"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    account = find_or_404(store.accounts, body["account_id"], "account")
    from_t = find_or_404(store.territories, body["from_territory_id"], "from territory")
    to_t = find_or_404(store.territories, body["to_territory_id"], "to territory")
    eff = parse_date(body["effective_date"], "effective_date")
    reason = opt_string(body, "reason")

    # Tier 4: plan must be COMMUNICATED or LOCKED
    if plan["status"] not in ("COMMUNICATED", "LOCKED"):
        raise ApiError("ERR_PLAN_NOT_COMMUNICATED",
                       "Change requests require plan status COMMUNICATED or LOCKED", 409)

    # Tier 5: cross-plan first, then from-territory alignment
    if account["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "account_id belongs to a different plan year", 409)
    if from_t["plan_year_id"] != plan["id"] or to_t["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "territory ids belong to a different plan year", 409)
    if account["assigned_territory_id"] != from_t["id"]:
        raise ApiError("ERR_FROM_TERRITORY_MISMATCH",
                       "from_territory_id != account's current assigned territory", 409)

    # Tier 6: effective date inside plan year
    p_start = date.fromisoformat(plan["start_date"])
    p_end = date.fromisoformat(plan["end_date"])
    if not (p_start <= eff <= p_end):
        raise ApiError("ERR_DATE_OUT_OF_PLAN_YEAR",
                       "effective_date falls outside the plan year", 422)

    # Tier 7: same territory / pending duplicate
    if to_t["id"] == from_t["id"]:
        raise ApiError("ERR_SAME_TERRITORY_TRANSFER",
                       "to_territory_id must differ from from_territory_id", 422)
    pending = [c for c in store.change_requests.values()
               if c["account_id"] == account["id"] and c["status"] in NON_TERMINAL]
    if pending:
        raise ApiError("ERR_CHANGE_ALREADY_PENDING",
                       "Account already has a change request in PENDING or APPROVED status", 409)

    cr = stamp_new({
        "plan_year_id": plan["id"],
        "account_id": account["id"],
        "from_territory_id": from_t["id"],
        "to_territory_id": to_t["id"],
        "effective_date": eff.isoformat(),
        "reason": reason,
        "created_by_user_id": ctx.user_id,
        "decided_by_user_id": None,
        "quota_transfer_cents": None,
        "status": "PENDING",
    })
    store.change_requests[cr["id"]] = cr
    return success_object(calc.ser_change_request(cr), status=201)


@bp.route("/sales-planning/change-requests", methods=["GET"])
def list_change_requests():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.change_requests.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [c for c in items if c["plan_year_id"] == v]
    if (v := request.args.get("account_id")) is not None:
        items = [c for c in items if c["account_id"] == v]
    if (v := request.args.get("from_territory_id")) is not None:
        items = [c for c in items if c["from_territory_id"] == v]
    if (v := request.args.get("to_territory_id")) is not None:
        items = [c for c in items if c["to_territory_id"] == v]
    if (v := request.args.get("status")) is not None:
        items = [c for c in items if c["status"] == v]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_change_request(c) for c in page], limit, offset, total)


@bp.route("/sales-planning/change-requests/<cid>", methods=["GET"])
def get_change_request(cid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    cr = find_or_404(store.change_requests, cid, "change request")
    return success_object(calc.ser_change_request(cr))


def _plan_gate_communicated(plan):
    if plan["status"] not in ("COMMUNICATED", "LOCKED"):
        raise ApiError("ERR_PLAN_NOT_COMMUNICATED",
                       "Operation requires plan status COMMUNICATED or LOCKED", 409)


@bp.route("/sales-planning/change-requests/<cid>/approve", methods=["POST"])
def approve_change_request(cid):
    ctx = get_user_context()
    require_role(ctx, MGR)
    cr = find_or_404(store.change_requests, cid, "change request")
    body = get_body()
    reject_unknown_fields(body, {"expected_plan_year_version"})
    plan = find_or_404(store.plan_years, cr["plan_year_id"], "plan year")
    _plan_gate_communicated(plan)

    # Segregation of duties
    if ctx.user_id == cr["created_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "Approver may not be the request's creator", 403)

    # OCC
    if "expected_plan_year_version" not in body or body["expected_plan_year_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "expected_plan_year_version is required", 400)
    expected = req_int(body, "expected_plan_year_version")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_plan_year_version does not match the plan's current version", 412)

    if cr["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot approve request in status {cr['status']}", 409)

    # Destination must be ACTIVE at approve
    to_t = find_or_404(store.territories, cr["to_territory_id"], "to territory")
    if to_t["status"] != "ACTIVE":
        raise ApiError("ERR_TERRITORY_NOT_ACTIVE",
                       "Destination territory is not ACTIVE", 409)

    cr["status"] = "APPROVED"
    cr["decided_by_user_id"] = ctx.user_id
    touch(cr)
    touch(plan)
    return success_object(calc.ser_change_request(cr))


@bp.route("/sales-planning/change-requests/<cid>/reject", methods=["POST"])
def reject_change_request(cid):
    ctx = get_user_context()
    require_role(ctx, MGR)
    cr = find_or_404(store.change_requests, cid, "change request")
    body = get_body()
    reject_unknown_fields(body, {"rejection_reason"})
    plan = find_or_404(store.plan_years, cr["plan_year_id"], "plan year")
    _plan_gate_communicated(plan)
    if cr["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot reject request in status {cr['status']}", 409)
    cr["status"] = "REJECTED"
    cr["decided_by_user_id"] = ctx.user_id
    touch(cr)
    return success_object(calc.ser_change_request(cr))


@bp.route("/sales-planning/change-requests/<cid>/return", methods=["POST"])
def return_change_request(cid):
    ctx = get_user_context()
    require_role(ctx, MGR)
    cr = find_or_404(store.change_requests, cid, "change request")
    body = get_body()
    reject_unknown_fields(body, {"return_reason"})
    plan = find_or_404(store.plan_years, cr["plan_year_id"], "plan year")
    _plan_gate_communicated(plan)
    if cr["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot return request in status {cr['status']}", 409)
    cr["status"] = "PENDING"
    cr["decided_by_user_id"] = None
    touch(cr)
    return success_object(calc.ser_change_request(cr))


@bp.route("/sales-planning/change-requests/<cid>/cancel", methods=["POST"])
def cancel_change_request(cid):
    ctx = get_user_context()
    require_role(ctx, ANALYST)
    cr = find_or_404(store.change_requests, cid, "change request")
    get_body()  # consume body if present (no declared inputs)
    plan = find_or_404(store.plan_years, cr["plan_year_id"], "plan year")

    # Ownership (tier 2)
    if ctx.user_id != cr["created_by_user_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Only the creator may cancel this change request", 403)
    _plan_gate_communicated(plan)

    if cr["status"] == "PENDING":
        cr["status"] = "CANCELLED"
    elif cr["status"] == "APPROVED":
        today = logical_today()
        if today >= date.fromisoformat(cr["effective_date"]):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Cannot cancel an APPROVED request once its effective date has been reached",
                           409)
        cr["status"] = "CANCELLED"
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot cancel request in status {cr['status']}", 409)
    touch(cr)
    return success_object(calc.ser_change_request(cr))


@bp.route("/sales-planning/change-requests/<cid>/apply", methods=["POST"])
def apply_change_request(cid):
    ctx = get_user_context()
    require_role(ctx, MGR)
    cr = find_or_404(store.change_requests, cid, "change request")
    get_body()
    plan = find_or_404(store.plan_years, cr["plan_year_id"], "plan year")
    _plan_gate_communicated(plan)

    if cr["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot apply request in status {cr['status']}", 409)

    today = logical_today()
    eff = date.fromisoformat(cr["effective_date"])
    if today < eff:
        raise ApiError("ERR_CHANGE_NOT_YET_EFFECTIVE",
                       "Current logical date is before the request's effective_date", 409)

    account = find_or_404(store.accounts, cr["account_id"], "account")
    if account["assigned_territory_id"] != cr["from_territory_id"]:
        raise ApiError("ERR_FROM_TERRITORY_MISMATCH",
                       "from_territory_id != account's current assigned territory", 409)
    to_t = find_or_404(store.territories, cr["to_territory_id"], "to territory")
    if to_t["status"] != "ACTIVE":
        raise ApiError("ERR_TERRITORY_NOT_ACTIVE", "Destination territory is not ACTIVE", 409)
    covered = any(a["territory_id"] == to_t["id"] and a["status"] == "ACTIVE"
                  for a in store.rep_assignments.values())
    if not covered:
        raise ApiError("ERR_TERRITORY_UNCOVERED",
                       "No ACTIVE rep assignment covers the destination territory", 409)

    from_t = find_or_404(store.territories, cr["from_territory_id"], "from territory")

    # Hop 1: move account
    account["assigned_territory_id"] = to_t["id"]
    account["assignment_source"] = "MANUAL_CHANGE"
    account["assignment_rule_id"] = None
    touch(account)

    # Hop 2: quota transfer
    p_start = date.fromisoformat(plan["start_date"])
    month_index = (eff.year - p_start.year) * 12 + (eff.month - p_start.month) + 1
    transfer = int((Decimal(account["annual_potential_cents"]) *
                    Decimal(12 - month_index) / Decimal(12)).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP))
    cr["quota_transfer_cents"] = transfer
    for t, sign in ((from_t, -1), (to_t, +1)):
        if t["final_quota_cents"] is not None:
            t["final_quota_cents"] += sign * transfer
            touch(t)
        elif t["assigned_quota_cents"] is not None:
            t["assigned_quota_cents"] += sign * transfer
            touch(t)

    # Hop 3: credit transition
    calc.run_credit_transition(plan, cr, today)

    # Hop 4: final share + ramp + pct on both territories
    calc.recompute_territory_assignment_cascade([from_t["id"], to_t["id"]])

    cr["status"] = "APPLIED"
    touch(cr)
    touch(plan)
    return success_object(calc.ser_change_request(cr))
