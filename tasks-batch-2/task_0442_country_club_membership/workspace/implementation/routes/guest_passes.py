"""Guest pass / sponsorship endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
import common
import computed
import services
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import guest_pass_out
from timeutil import parse_iso

bp = Blueprint("guest_passes", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]


@bp.post("/guest-passes")
def create_guest_pass():
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    body = common.get_body()
    common.require_fields(body, ["club_id", "sponsor_membership_id", "guest_name", "visit_date"])
    club_id = common.require_string(body, "club_id")
    common.get_club(club_id)
    sponsor = common.get_membership(common.require_string(body, "sponsor_membership_id"))
    # Sponsor must be the acting member (priority 4).
    services.assert_owner(role, user_id, sponsor["id"])
    guest_name = common.require_string(body, "guest_name")
    visit_date = body["visit_date"]
    parse_iso(visit_date, err=errors.validation)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "club_id": club_id,
            "sponsor_membership_id": sponsor["id"],
            "guest_name": guest_name,
            "visit_date": visit_date,
            "status": "REGISTERED",
            "fee_chit_id": None,
        }
    )
    db.guest_passes[rec["id"]] = rec
    return success_object(guest_pass_out(rec), status=201)


@bp.get("/guest-passes/<gid>")
def get_guest_pass(gid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_guest_pass(gid)
    return success_object(guest_pass_out(rec), status=200)


@bp.get("/guest-passes")
def list_guest_passes():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.guest_passes.values())
    sponsor_id = request.args.get("sponsor_membership_id")
    club_id = request.args.get("club_id")
    fee_chit_id = request.args.get("fee_chit_id")
    if sponsor_id is not None:
        records = [r for r in records if r["sponsor_membership_id"] == sponsor_id]
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    if fee_chit_id is not None:
        records = [r for r in records if r.get("fee_chit_id") == fee_chit_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [guest_pass_out(r) for r in page]
    return success_array(data, limit, offset, total)


@bp.post("/guest-passes/<gid>/check-in")
def check_in(gid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    rec = common.get_guest_pass(gid)
    # State precondition first (PRD §2.11).
    if rec["status"] != "REGISTERED":
        raise errors.invalid_state("GuestPass is not REGISTERED")
    sponsor = db.memberships[rec["sponsor_membership_id"]]
    club = db.clubs[rec["club_id"]]
    # Sponsor must be ACTIVE.
    if sponsor["account_status"] != "ACTIVE":
        raise errors.membership_not_active("Sponsor membership is not ACTIVE")
    # Guest-visit quota: strict < cap (PRD §3.5).
    used = computed.membership_guest_visits_used(sponsor["id"])
    if used >= club["guest_visits_cap_per_period"]:
        raise errors.guest_quota_exceeded()
    category = db.categories[sponsor["category_id"]]
    # Cascade: create GUEST_FEE chit on sponsor, debit balance.
    chit = services.post_chit(
        club_id=rec["club_id"],
        membership_id=sponsor["id"],
        amount_cents=category["guest_fee_cents"],
        kind="GUEST_FEE",
        bump_membership=True,
    )
    rec["status"] = "CHECKED_IN"
    rec["fee_chit_id"] = chit["id"]
    rec["checked_in_period_index"] = club["billing_period_index"]
    db.touch(rec)
    computed.refresh_membership_computeds(sponsor["id"])
    return success_object(guest_pass_out(rec), status=200)


@bp.post("/guest-passes/<gid>/cancel")
def cancel(gid):
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    rec = common.get_guest_pass(gid)
    services.assert_owner(role, user_id, rec["sponsor_membership_id"])
    if rec["status"] != "REGISTERED":
        raise errors.invalid_state("GuestPass is not REGISTERED")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success_object(guest_pass_out(rec), status=200)
