"""Waitlist entry endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import common
import computed
import services
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import waitlist_out

bp = Blueprint("waitlist", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]


@bp.post("/waitlist-entries")
def create_entry():
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    body = common.get_body()
    common.require_fields(body, ["club_id", "category_id", "applicant_name"])
    club_id = common.require_string(body, "club_id")
    common.get_club(club_id)
    category = common.get_category(common.require_string(body, "category_id"))
    applicant_name = common.require_string(body, "applicant_name")

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "club_id": club_id,
            "category_id": category["id"],
            "applicant_name": applicant_name,
            "status": "WAITING",
            "offered_period_index": None,
            "created_membership_id": None,
        }
    )
    db.waitlist_entries[rec["id"]] = rec
    return success_object(waitlist_out(rec), status=201)


@bp.get("/waitlist-entries/<wid>")
def get_entry(wid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_waitlist(wid)
    return success_object(waitlist_out(rec), status=200)


@bp.get("/waitlist-entries")
def list_entries():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.waitlist_entries.values())
    category_id = request.args.get("category_id")
    club_id = request.args.get("club_id")
    created_membership_id = request.args.get("created_membership_id")
    if category_id is not None:
        records = [r for r in records if r["category_id"] == category_id]
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    if created_membership_id is not None:
        records = [r for r in records if r.get("created_membership_id") == created_membership_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [waitlist_out(r) for r in page]
    return success_array(data, limit, offset, total)


@bp.post("/waitlist-entries/<wid>/offer")
def offer(wid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    rec = common.get_waitlist(wid)
    if rec["status"] != "WAITING":
        raise errors.invalid_state("WaitlistEntry is not WAITING")
    category = db.categories[rec["category_id"]]
    club = db.clubs[rec["club_id"]]
    if computed.category_active_member_count(category["id"]) >= category["capacity"]:
        raise errors.category_at_capacity()
    rec["status"] = "OFFERED"
    rec["offered_period_index"] = club["billing_period_index"]
    db.touch(rec)
    return success_object(waitlist_out(rec), status=200)


@bp.post("/waitlist-entries/<wid>/accept")
def accept(wid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    rec = common.get_waitlist(wid)
    if rec["status"] != "OFFERED":
        raise errors.invalid_state("WaitlistEntry is not OFFERED")
    category = db.categories[rec["category_id"]]
    club = db.clubs[rec["club_id"]]
    body = common.get_body()
    # OCC on category version, after state precondition (PRD §2.11).
    expected = body.get("expected_category_version")
    if expected != category["version"]:
        raise errors.stale_version("expected_category_version does not match")
    # Capacity re-check (priority 11).
    if computed.category_active_member_count(category["id"]) >= category["capacity"]:
        raise errors.category_at_capacity()

    # Cascade: create a PENDING membership for this category, then activate it.
    m = db.base_record(common_fields=True)
    m.update(
        {
            "club_id": rec["club_id"],
            "category_id": category["id"],
            "primary_member_id": None,
            "holder_name": rec["applicant_name"],
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
    db.memberships[m["id"]] = m
    services.apply_activation(m)  # bumps category version among its side effects

    rec["status"] = "ACCEPTED"
    rec["created_membership_id"] = m["id"]
    db.touch(rec)
    return success_object(waitlist_out(rec), status=200)


@bp.post("/waitlist-entries/<wid>/decline")
def decline(wid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    rec = common.get_waitlist(wid)
    if rec["status"] != "OFFERED":
        raise errors.invalid_state("WaitlistEntry is not OFFERED")
    club = db.clubs[rec["club_id"]]
    rec["status"] = "DECLINED"
    db.touch(rec)
    # Cascade: promote the next WAITING entry for this category.
    services.promote_earliest_waiting(rec["category_id"], club)
    return success_object(waitlist_out(rec), status=200)
