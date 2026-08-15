"""Member endpoints."""

from flask import Blueprint, request
from db import db
from middleware import require_roles
from validate import get_body, req_string, opt_string, parse_pagination
from response import success_object, success_list
from errors import not_found, invalid_state, already_terminal, self_service_forbidden, invalid_enum
from services.core import recompute_member, member_view

bp = Blueprint("members", __name__)

MEMBER_STATUSES = {"ACTIVE", "SUSPENDED", "CLOSED"}


def get_member_or_404(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise not_found("Member not found.")
    return m


def email_taken(email, exclude_id=None):
    for m in db.members.values():
        if m["email"] == email and m["id"] != exclude_id:
            return True
    return False


@bp.post("/api/members")
def create_member():
    require_roles("ProgramAdmin")
    body = get_body()
    email = req_string(body, "email")
    full_name = req_string(body, "full_name")
    home_site_id = req_string(body, "home_site_id")
    # band 5: body FK existence
    if home_site_id not in db.sites:
        raise not_found("home_site_id does not resolve to an existing site.")
    # uniqueness (band 8): member.email unique. Scaffold defines no dedicated
    # duplicate-email error id; reuse the uniqueness error id at 409.
    if email_taken(email):
        from errors import ApiError
        raise ApiError("ERR_DUPLICATE_LOT_CODE", 409,
                       "A member with this email already exists.")
    member = {
        "email": email,
        "full_name": full_name,
        "home_site_id": home_site_id,
        "status": "ACTIVE",
        "active_checkout_count": 0,
        "overdue_checkout_count": 0,
        "terminal_checkout_count": 0,
        "verified_return_count": 0,
        "simple_return_rate": 0.0,
        "decay_weighted_return_score": 0.0,
        "standing_tier": "STANDARD",
        "effective_borrow_limit": 5,
        "credits_earned_total": 0,
        "credits_redeemed_total": 0,
        "credits_expired_total": 0,
        "credits_revoked_total": 0,
        "credits_balance": 0,
    }
    db.stamp_new(member)
    db.members[member["id"]] = member
    return success_object(member_view(member), 201)


@bp.get("/api/members")
def list_members():
    require_roles("ProgramAdmin")
    limit, offset = parse_pagination()
    home_site_id = request.args.get("home_site_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in MEMBER_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.members.values(), key=lambda m: m["_seq"])
    if home_site_id:
        items = [m for m in items if m["home_site_id"] == home_site_id]
    if status_f:
        items = [m for m in items if m["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([member_view(m) for m in page], limit, offset, total)


@bp.get("/api/members/<member_id>")
def get_member(member_id):
    user_id, role = require_roles("ProgramAdmin", "Member")
    m = get_member_or_404(member_id)
    # band 12 ownership
    if role == "Member" and m["id"] != user_id:
        raise self_service_forbidden("Member may read only its own record.")
    return success_object(member_view(m))


@bp.patch("/api/members/<member_id>")
def patch_member(member_id):
    require_roles("ProgramAdmin")
    m = get_member_or_404(member_id)
    body = get_body()
    full_name = opt_string(body, "full_name")
    home_site_id = opt_string(body, "home_site_id")
    new_status = opt_enum(body, "status", MEMBER_STATUSES, default=None)
    if home_site_id is not None and home_site_id not in db.sites:
        raise not_found("home_site_id does not resolve to an existing site.")

    recompute_member(m)
    # band 14: CLOSED is terminal — any PATCH against it locks down
    if m["status"] == "CLOSED":
        raise already_terminal("Member is CLOSED (terminal).")
    if new_status is not None and new_status != m["status"]:
        if new_status == "CLOSED":
            if m["status"] not in ("ACTIVE", "SUSPENDED"):
                raise invalid_state("Cannot close from current status.")
            if m["active_checkout_count"] != 0 or m["credits_balance"] != 0:
                raise invalid_state(
                    "Member has live checkouts or outstanding credit balance.")
            m["status"] = "CLOSED"
        else:
            # only ACTIVE<->CLOSED and SUSPENDED<->CLOSED are declared transitions;
            # no manual SUSPENDED/ACTIVE toggle exists
            raise invalid_state("Unsupported member status transition.")
    if full_name is not None:
        m["full_name"] = full_name
    if home_site_id is not None:
        m["home_site_id"] = home_site_id
    db.touch(m)
    return success_object(member_view(m))


@bp.get("/api/members/<member_id>/credit-summary")
def credit_summary(member_id):
    user_id, role = require_roles("ProgramAdmin", "Member")
    m = get_member_or_404(member_id)
    if role == "Member" and m["id"] != user_id:
        raise self_service_forbidden("Member may read only its own credit summary.")
    recompute_member(m)
    return success_object({
        "credits_earned_total": m["credits_earned_total"],
        "credits_redeemed_total": m["credits_redeemed_total"],
        "credits_expired_total": m["credits_expired_total"],
        "credits_revoked_total": m["credits_revoked_total"],
        "credits_balance": m["credits_balance"],
    })
