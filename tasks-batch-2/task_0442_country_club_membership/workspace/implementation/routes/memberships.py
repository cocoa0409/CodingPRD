"""Membership lifecycle + payments (PRD §3.2, §3.3, §3.6)."""
from flask import Blueprint, request

import db
import errors
import common
import computed
import services
import billing
import calculations as calc
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import membership_out

bp = Blueprint("memberships", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]


@bp.post("/memberships")
def create_membership():
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    body = common.get_body()
    common.require_fields(body, ["club_id", "category_id", "holder_name"])
    club_id = common.require_string(body, "club_id")
    common.get_club(club_id)
    category_id = common.require_string(body, "category_id")
    common.get_category(category_id)
    holder_name = common.require_string(body, "holder_name")
    primary_member_id = body.get("primary_member_id")
    if primary_member_id is not None:
        common.get_membership(primary_member_id)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "club_id": club_id,
            "category_id": category_id,
            "primary_member_id": primary_member_id,
            "holder_name": holder_name,
            "account_status": "PENDING",
            "billing_status": "CURRENT",
            "charge_balance_cents": 0,
            "fb_spend_period_cents": 0,
            "fb_credit_carried_cents": 0,
            "refund_owed_cents": 0,
            "activated_period_index": None,
            "guest_visits_used_period": 0,
            "payment_credit_cents": 0,
        }
    )
    db.memberships[rec["id"]] = rec
    return success_object(membership_out(rec, computed), status=201)


@bp.get("/memberships/<mid>")
def get_membership(mid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_membership(mid)
    return success_object(membership_out(rec, computed), status=200)


@bp.get("/memberships")
def list_memberships():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.memberships.values())
    club_id = request.args.get("club_id")
    category_id = request.args.get("category_id")
    primary_member_id = request.args.get("primary_member_id")
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    if category_id is not None:
        records = [r for r in records if r["category_id"] == category_id]
    if primary_member_id is not None:
        records = [r for r in records if r.get("primary_member_id") == primary_member_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [membership_out(r, computed) for r in page]
    return success_array(data, limit, offset, total)


@bp.post("/memberships/<mid>/activate")
def activate(mid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    m = common.get_membership(mid)
    # State precondition before capacity gate (PRD §2.11 / §3.2).
    if m["account_status"] != "PENDING":
        raise errors.invalid_state("Membership is not PENDING")
    category = db.categories[m["category_id"]]
    count = computed.category_active_member_count(category["id"])
    if count >= category["capacity"]:
        raise errors.category_at_capacity()
    services.apply_activation(m)
    return success_object(membership_out(m, computed), status=200)


@bp.post("/memberships/<mid>/suspend")
def suspend(mid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    m = common.get_membership(mid)
    if m["account_status"] != "ACTIVE":
        raise errors.invalid_state("Membership is not ACTIVE")
    m["account_status"] = "SUSPENDED"
    db.touch(m)
    # Suspended seats are still held; active_member_count unchanged (PRD §3.3).
    return success_object(membership_out(m, computed), status=200)


@bp.post("/memberships/<mid>/reinstate")
def reinstate(mid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    m = common.get_membership(mid)
    if m["account_status"] != "SUSPENDED":
        raise errors.invalid_state("Membership is not SUSPENDED")
    m["account_status"] = "ACTIVE"
    db.touch(m)
    return success_object(membership_out(m, computed), status=200)


@bp.post("/memberships/<mid>/resign")
def resign(mid):
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    m = common.get_membership(mid)
    # Member may only resign their own membership (PRD §2.1 priority 4).
    services.assert_owner(role, user_id, m["id"])
    if m["account_status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Membership is not ACTIVE or SUSPENDED")
    category = db.categories[m["category_id"]]
    club = db.clubs[m["club_id"]]
    balance = computed.membership_charge_balance(m["id"])
    refund = calc.resignation_refund(
        category["refundable_equity_cents"],
        club["resignation_refund_pct"],
        balance,
    )
    m["account_status"] = "RESIGNED_PENDING"
    m["refund_owed_cents"] = refund
    db.touch(m)
    return success_object(membership_out(m, computed), status=200)


@bp.post("/memberships/<mid>/settle-resignation")
def settle_resignation(mid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    m = common.get_membership(mid)
    if m["account_status"] != "RESIGNED_PENDING":
        raise errors.invalid_state("Membership is not RESIGNED_PENDING")
    balance = computed.membership_charge_balance(m["id"])
    if balance != 0:
        raise errors.outstanding_balance()
    category = db.categories[m["category_id"]]
    club = db.clubs[m["club_id"]]
    m["account_status"] = "RESIGNED"
    db.touch(m)
    # Recompute the freed-seat count and bump category version (PRD §3.3).
    computed.refresh_category_count(category["id"])
    db.touch(category)
    # Cascade: promote earliest WAITING for this category to OFFERED.
    services.promote_earliest_waiting(category["id"], club)
    return success_object(membership_out(m, computed), status=200)


@bp.post("/memberships/<mid>/payments")
def payment(mid):
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    m = common.get_membership(mid)
    services.assert_owner(role, user_id, m["id"])
    body = common.get_body()
    common.require_fields(body, ["amount_cents"])
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise errors.payment_invalid("amount_cents must be a positive integer")
    balance = computed.membership_charge_balance(m["id"])
    if amount > balance:
        raise errors.payment_invalid("amount_cents exceeds outstanding charge balance")
    billing.apply_payment(m, amount)
    return success_object(membership_out(m, computed), status=200)
