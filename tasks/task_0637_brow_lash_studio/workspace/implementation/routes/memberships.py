"""Membership routes: enroll, list, get, credit-ledger, lifecycle (PRD §3.4)."""
from flask import Blueprint, request

import errors
from common import (bad_request, get_json_body, parse_pagination, paginate,
                    require_int, require_str, sort_by_created, stamp_create)
from db import store
from lookups import (get_member_or_404, get_membership_or_404, ownership_member,
                     parse_dt_or_400)
from middleware import get_user_context, require_role
from response import success_list, success_object
from services import credits, membership_lifecycle
import serialize

bp = Blueprint("memberships", __name__)


@bp.route("/memberships", methods=["POST"])
def enroll_membership():
    _, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk"})
    body = get_json_body()
    member_id = require_str(body, "member_id")
    member = get_member_or_404(member_id)
    plan_id = require_str(body, "plan_id")
    plan = store.membership_plans.get(plan_id)
    if not plan:
        # Plan FK miss: no dedicated error; nearest applicable not-found.
        raise errors.ApiError(errors.ERR_STUDIO_NOT_FOUND, 404, "Membership plan not found.")
    # Plan must belong to same studio as the member (PRD §2.8).
    if plan["studio_id"] != member["studio_id"]:
        raise errors.ApiError(errors.ERR_STUDIO_NOT_FOUND, 404, "Plan not in member's studio.")
    cycle_anchor = parse_dt_or_400(body, "cycle_anchor_utc")

    initial_credits = body.get("initial_credits", plan["monthly_credit_allotment"])
    if not isinstance(initial_credits, int) or isinstance(initial_credits, bool):
        raise bad_request("initial_credits must be an integer.")
    if initial_credits < 0:
        raise bad_request("initial_credits must be >= 0.")

    rec = {
        "member_id": member["id"],
        "plan_id": plan["id"],
        "cycle_anchor_utc": cycle_anchor,
        "cycles_closed": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    store.memberships[rec["id"]] = rec
    # A GRANT ledger entry of +initial_credits is appended (PRD §3.4).
    credits.append_ledger_entry(rec["id"], initial_credits, "GRANT", rec["id"])
    return success_object(serialize.membership_out(rec), status=201)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    plan_id = request.args.get("plan_id")
    items = list(store.memberships.values())
    if member_id is not None:
        items = [m for m in items if m["member_id"] == member_id]
    if plan_id is not None:
        items = [m for m in items if m["plan_id"] == plan_id]
    if role == "Member":
        items = [m for m in items if m["member_id"] == user_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.membership_out(m) for m in page], limit, offset, total)


@bp.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    ms = get_membership_or_404(mid)
    ownership_member(role, user_id, ms["member_id"])
    return success_object(serialize.membership_out(ms))


@bp.route("/memberships/<mid>/credit-ledger", methods=["GET"])
def get_credit_ledger(mid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    ms = get_membership_or_404(mid)
    ownership_member(role, user_id, ms["member_id"])
    limit, offset = parse_pagination()
    items = credits.ledger_for_membership(ms["id"])  # already sorted ascending
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.credit_ledger_entry_out(e) for e in page], limit, offset, total)


@bp.route("/memberships/<mid>/close-cycle", methods=["POST"])
def close_cycle(mid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    ms = get_membership_or_404(mid)
    body = get_json_body()
    expected_version = require_int(body, "expected_membership_version")
    membership_lifecycle.close_cycle(ms, expected_version)
    return success_object(serialize.membership_out(ms))


@bp.route("/memberships/<mid>/flag-past-due", methods=["POST"])
def flag_past_due(mid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    ms = get_membership_or_404(mid)
    membership_lifecycle.flag_past_due(ms)
    return success_object(serialize.membership_out(ms))


@bp.route("/memberships/<mid>/settle-dues", methods=["POST"])
def settle_dues(mid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    ms = get_membership_or_404(mid)
    membership_lifecycle.settle_dues(ms)
    return success_object(serialize.membership_out(ms))


@bp.route("/memberships/<mid>/reactivate", methods=["POST"])
def reactivate(mid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    ms = get_membership_or_404(mid)
    membership_lifecycle.reactivate(ms)
    return success_object(serialize.membership_out(ms))


@bp.route("/memberships/<mid>/cancel-membership", methods=["POST"])
def cancel_membership(mid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    ms = get_membership_or_404(mid)
    membership_lifecycle.cancel_membership(ms)
    return success_object(serialize.membership_out(ms))
