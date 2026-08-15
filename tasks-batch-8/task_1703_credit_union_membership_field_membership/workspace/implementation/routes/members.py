"""Member endpoints, tier review, and member-scoped sub-resource lists."""
from flask import Blueprint, request

import db
from auth import require_roles, check_member_owns, MEMBER, STAFF_ROLES
from errors import ApiError
from response import ok_object, paginate, now_iso
from serializers import (serialize_member, serialize_account, serialize_ballot,
                         serialize_review)
from services import calc
from services.sweep import bump
from validators import get_body, req_int, opt_str_or_null

bp = Blueprint("members", __name__)

ALL_READ = STAFF_ROLES | {MEMBER}


def get_member_or_404(mid):
    m = db.members.get(mid)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", f"member {mid} not found")
    return m


@bp.get("/credit-union/members")
def list_members():
    uid, role = require_roles(ALL_READ)
    items = list(db.members.values())
    if role == MEMBER:
        items = [m for m in items if m["id"] == uid]
    for f in ("status", "tier", "segment_id", "sponsor_member_id", "application_id"):
        v = request.args.get(f)
        if v is not None:
            items = [m for m in items if m.get(f) == v]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return paginate([serialize_member(m) for m in items])


@bp.get("/credit-union/members/<mid>")
def get_member(mid):
    uid, role = require_roles(ALL_READ)
    check_member_owns(uid, role, mid)
    return ok_object(serialize_member(get_member_or_404(mid)), 200)


@bp.patch("/credit-union/members/<mid>")
def patch_member(mid):
    require_roles({"MembershipOfficer"})
    body = get_body()
    expected_member_version = req_int(body, "expected_member_version")
    fields = {}
    for f in ("mailing_address", "email", "phone"):
        present, v = opt_str_or_null(body, f)
        if present:
            fields[f] = v
    member = get_member_or_404(mid)
    if expected_member_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION",
                       "expected_member_version does not match the member version")
    for f, v in fields.items():
        member[f] = v
    bump(member)
    return ok_object(serialize_member(member), 200)


@bp.post("/credit-union/members/<mid>/tier-review")
def tier_review(mid):
    require_roles({"OperationsOfficer"})
    member = get_member_or_404(mid)
    member["tier"] = calc.trailing_90_average_tier(member, db.clock.current_date())
    member["last_tier_review_at"] = now_iso()
    bump(member)
    return ok_object(serialize_member(member), 200)


@bp.get("/credit-union/members/<mid>/share-accounts")
def list_member_accounts(mid):
    uid, role = require_roles(ALL_READ)
    check_member_owns(uid, role, mid)
    get_member_or_404(mid)
    items = [a for a in db.accounts.values() if a["member_id"] == mid]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return paginate([serialize_account(a) for a in items])


@bp.get("/credit-union/members/<mid>/ballots")
def list_member_ballots(mid):
    uid, role = require_roles(ALL_READ)
    check_member_owns(uid, role, mid)
    get_member_or_404(mid)
    items = [b for b in db.ballots.values() if b["member_id"] == mid]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    return paginate([serialize_ballot(b) for b in items])


@bp.get("/credit-union/members/<mid>/eligibility-reviews")
def list_member_reviews(mid):
    require_roles(STAFF_ROLES)
    get_member_or_404(mid)
    items = [r for r in db.reviews.values() if r["member_id"] == mid]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate([serialize_review(r) for r in items])
