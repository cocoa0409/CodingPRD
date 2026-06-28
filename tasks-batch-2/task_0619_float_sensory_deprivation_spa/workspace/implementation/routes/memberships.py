"""Membership lifecycle: open, activate, renew (OCC), mark-past-due, cancel."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import serializers
from clock import clock
from constants import CYCLE_LENGTH_DAYS
from db import db, stamp_create, touch
from helpers import get_json_body, require_fields, parse_pagination, paginate
from middleware import authenticate, require_role
from response import success
from services.ledger import add_credit_entry, add_payment
from services.pricing import refund_valuation

bp = Blueprint("memberships", __name__)


@bp.route("/memberships", methods=["POST"])
def create_membership():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    body = get_json_body()
    require_fields(body, ["member_id", "plan_id"])
    member = db.members.get(body["member_id"])
    if member is None:
        raise errors.not_found("Member not found.")
    plan = db.plans.get(body["plan_id"])
    if plan is None:
        raise errors.not_found("Plan not found.")
    record = {
        "member_id": body["member_id"],
        "plan_id": body["plan_id"],
        "status": "PENDING",
        "credit_balance": 0,
        "cycle_index": 0,
        "cycle_start_utc": None,
        "cycle_end_utc": None,
        "monthly_fee_cents_snapshot": None,
    }
    stamp_create(record)
    db.memberships[record["id"]] = record
    return success(serializers.membership_out(record), status=201)


@bp.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    m = db.memberships.get(mid)
    if m is None:
        raise errors.not_found("Membership not found.")
    if principal.is_member() and m["member_id"] != principal.user_id:
        raise errors.forbidden()
    return success(serializers.membership_out(m), status=200)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    records = list(db.memberships.values())
    member_id = request.args.get("member_id")
    plan_id = request.args.get("plan_id")
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if principal.is_member():
        records = [r for r in records if r["member_id"] == principal.user_id]
    page, meta = paginate(records, limit, offset)
    return success([serializers.membership_out(r) for r in page], status=200, pagination=meta)


@bp.route("/memberships/<mid>/activate", methods=["POST"])
def activate_membership(mid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    m = db.memberships.get(mid)
    if m is None:
        raise errors.not_found("Membership not found.")
    plan = db.plans.get(m["plan_id"])

    if m["status"] == "PENDING":
        # Plan must still be open to new memberships.
        if plan is None or not plan["active"]:
            raise errors.plan_inactive()
        now = clock.now()
        m["cycle_index"] = 0
        m["cycle_start_utc"] = now
        m["cycle_end_utc"] = now + timedelta(days=CYCLE_LENGTH_DAYS)
        m["monthly_fee_cents_snapshot"] = plan["monthly_fee_cents"]
        m["status"] = "ACTIVE"
        add_credit_entry(m, "GRANT", plan["included_floats_per_cycle"], booking_id=None)
        touch(m)
    elif m["status"] == "PAST_DUE":
        # Return from PAST_DUE: just unfreeze; no re-grant, no cycle move.
        m["status"] = "ACTIVE"
        touch(m)
    else:
        raise errors.invalid_state("Membership is not PENDING or PAST_DUE.")
    return success(serializers.membership_out(m), status=200)


@bp.route("/memberships/<mid>/renew", methods=["POST"])
def renew_membership(mid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    body = get_json_body()
    require_fields(body, ["expected_membership_version"])
    m = db.memberships.get(mid)
    if m is None:
        raise errors.not_found("Membership not found.")
    if m["status"] != "ACTIVE":
        raise errors.invalid_state("Membership is not ACTIVE.")
    # OCC check (priority 13) after state legality.
    expected = body["expected_membership_version"]
    if expected != m["version"]:
        raise errors.stale_version()

    plan = db.plans.get(m["plan_id"])
    pre_balance = m["credit_balance"]
    rollover_cap = plan["rollover_cap"]
    overflow = max(0, pre_balance - rollover_cap)
    # PINNED order: (1) EXPIRE overflow, (2) GRANT new floats.
    if overflow > 0:
        add_credit_entry(m, "EXPIRE", -overflow, booking_id=None)
    add_credit_entry(m, "GRANT", plan["included_floats_per_cycle"], booking_id=None)

    m["cycle_index"] = m["cycle_index"] + 1
    old_end = m["cycle_end_utc"]
    m["cycle_start_utc"] = old_end
    m["cycle_end_utc"] = old_end + timedelta(days=CYCLE_LENGTH_DAYS)
    touch(m)  # version += 1
    return success(serializers.membership_out(m), status=200)


@bp.route("/memberships/<mid>/mark-past-due", methods=["POST"])
def mark_past_due(mid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    m = db.memberships.get(mid)
    if m is None:
        raise errors.not_found("Membership not found.")
    if m["status"] != "ACTIVE":
        raise errors.invalid_state("Membership is not ACTIVE.")
    m["status"] = "PAST_DUE"
    touch(m)
    return success(serializers.membership_out(m), status=200)


@bp.route("/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    m = db.memberships.get(mid)
    if m is None:
        raise errors.not_found("Membership not found.")
    if principal.is_member() and m["member_id"] != principal.user_id:
        raise errors.forbidden()
    if m["status"] == "CANCELLED":
        raise errors.invalid_state("Membership already CANCELLED.")

    now = clock.now()
    # CASCADE step 1+2: forfeit remaining credits -> balance 0.
    if m["credit_balance"] > 0:
        add_credit_entry(m, "FORFEIT", -m["credit_balance"], booking_id=None)
    # Refund valuation (authoritative prorated value).
    refund = refund_valuation(m, now)
    m["status"] = "CANCELLED"
    touch(m)
    if refund > 0:
        add_payment("SESSION_REFUND", "CASH", -refund, booking_id=None, gift_card_id=None)
    return success(serializers.membership_out(m), status=200)
