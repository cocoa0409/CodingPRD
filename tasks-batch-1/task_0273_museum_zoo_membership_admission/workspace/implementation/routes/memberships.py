"""Membership, HouseholdMember, GuestPass routes."""
from flask import Blueprint, request

import db
import serializers as S
from errors import ApiError, ERR_HOUSEHOLD_FULL, not_owner
from listing import list_response
from middleware import get_identity, require_role
from response import ok, created
from routes.helpers import resolve, ensure_owns_membership
from services import membership_svc
import validate as V

bp = Blueprint("memberships", __name__)

VALID_RELATIONSHIP = {"SPOUSE", "CHILD", "PARTNER", "OTHER"}
VALID_STATUS = {"PENDING_PAYMENT", "ACTIVE", "GRACE", "EXPIRED", "CANCELLED"}


# --------------------------- Membership ---------------------------

@bp.post("/memberships")
def create_membership():
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice", "MembershipAdmin"})
    body = V.get_body()
    # Left-to-right existence: plan_id then primary_patron_id.
    plan_id = V.require_str(body, "plan_id")
    plan = resolve(db.membership_plans, plan_id)
    primary_patron_id = V.require_str(body, "primary_patron_id")
    patron = resolve(db.patrons, primary_patron_id)
    # Patron creating own membership: primary_patron_id must equal X-User-ID.
    if role == "Patron" and primary_patron_id != user_id:
        raise not_owner("Patron may only create their own membership")
    auto_renew = V.opt_bool(body, "auto_renew", False)
    donation_cents = V.opt_int_nonneg(body, "donation_cents", 0)
    rec = {
        "plan_id": plan["id"],
        "primary_patron_id": patron["id"],
        "status": "PENDING_PAYMENT",
        "auto_renew": auto_renew,
        "started_at": None,
        "expires_at": None,
        "grace_until": None,
        "term_count": 1,
        "last_paid_fee_cents": None,
    }
    db.stamp_create(rec)
    if donation_cents > 0:
        rec["_pending_donation_cents"] = donation_cents
    db.memberships[rec["id"]] = rec
    return created(S.membership(db.public(rec)))


@bp.get("/memberships/<rid>")
def read_membership(rid):
    user_id, role = get_identity()
    rec = resolve(db.memberships, rid)
    ensure_owns_membership(user_id, role, rec)
    return ok(S.membership(db.public(rec)))


@bp.get("/memberships")
def list_memberships():
    _, role = get_identity()
    require_role(role, {"BoxOffice", "MembershipAdmin"})
    filters = {
        "plan_id": request.args.get("plan_id"),
        "primary_patron_id": request.args.get("primary_patron_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.memberships, lambda r: S.membership(db.public(r)), filters)


@bp.post("/memberships/<rid>/renew")
def renew_membership(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    rec = resolve(db.memberships, rid)
    ensure_owns_membership(user_id, role, rec)
    body = V.get_body()
    expected_version = V.require_int_nonneg(body, "expected_membership_version")
    donation_cents = V.opt_int_nonneg(body, "donation_cents", 0)
    membership_svc.renew_manual(rec, expected_version, donation_cents)
    return ok(S.membership(db.public(rec)))


@bp.post("/memberships/<rid>/cancel")
def cancel_membership(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    rec = resolve(db.memberships, rid)
    ensure_owns_membership(user_id, role, rec)
    membership_svc.cancel(rec)
    return ok(S.membership(db.public(rec)))


@bp.patch("/memberships/<rid>/auto-renew")
def toggle_auto_renew(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    rec = resolve(db.memberships, rid)
    ensure_owns_membership(user_id, role, rec)
    body = V.get_body()
    auto_renew = V.require_bool(body, "auto_renew")
    rec["auto_renew"] = auto_renew
    db.touch(rec)
    return ok(S.membership(db.public(rec)))


# --------------------------- HouseholdMember ---------------------------

@bp.post("/memberships/<rid>/household-members")
def add_household_member(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    membership = resolve(db.memberships, rid)
    ensure_owns_membership(user_id, role, membership)
    body = V.get_body()
    full_name = V.require_str(body, "full_name")
    relationship = V.require_enum(body, "relationship", VALID_RELATIONSHIP)
    plan = db.membership_plans[membership["plan_id"]]
    active_count = sum(
        1 for hm in db.household_members.values()
        if hm["membership_id"] == membership["id"] and hm.get("active")
    )
    if active_count + 1 > plan["household_max"]:
        raise ApiError(ERR_HOUSEHOLD_FULL, 409, "Household is full")
    rec = {
        "membership_id": membership["id"],
        "full_name": full_name,
        "relationship": relationship,
        "active": True,
    }
    db.stamp_create(rec)
    db.household_members[rec["id"]] = rec
    return created(S.household_member(db.public(rec)))


@bp.get("/household-members/<rid>")
def read_household_member(rid):
    get_identity()
    rec = resolve(db.household_members, rid)
    return ok(S.household_member(db.public(rec)))


@bp.get("/household-members")
def list_household_members():
    get_identity()
    filters = {"membership_id": request.args.get("membership_id")}
    return list_response(db.household_members, lambda r: S.household_member(db.public(r)), filters)


@bp.delete("/household-members/<rid>")
def remove_household_member(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    rec = resolve(db.household_members, rid)
    membership = db.memberships.get(rec["membership_id"])
    if membership is not None:
        ensure_owns_membership(user_id, role, membership)
    rec["active"] = False
    db.touch(rec)
    return ok(S.household_member(db.public(rec)))


# --------------------------- GuestPass ---------------------------

@bp.get("/guest-passes/<rid>")
def read_guest_pass(rid):
    get_identity()
    rec = resolve(db.guest_passes, rid)
    return ok(S.guest_pass(db.public(rec)))


@bp.get("/guest-passes")
def list_guest_passes():
    get_identity()
    filters = {
        "membership_id": request.args.get("membership_id"),
        "status": request.args.get("status"),
        "reserved_order_id": request.args.get("reserved_order_id"),
    }
    return list_response(db.guest_passes, lambda r: S.guest_pass(db.public(r)), filters)


@bp.get("/guest-passes/<rid>/tickets")
def list_guest_pass_tickets(rid):
    get_identity()
    resolve(db.guest_passes, rid)
    filters = {"guest_pass_id": rid}
    return list_response(db.admission_tickets, lambda r: S.admission_ticket(db.public(r)), filters)
