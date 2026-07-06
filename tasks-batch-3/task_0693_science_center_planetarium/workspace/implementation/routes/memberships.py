"""Membership endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, new_record, touch
from clock import iso
from errors import err, ERR_PARTY_SIZE_INVALID, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_enum,
    require_int,
    optional_int,
    parse_pagination,
    paginate,
)
from services.lookups import get_membership
from services.serialize import membership_view
from services.calculations import astc_reciprocal_admit

bp = Blueprint("memberships", __name__)

TIERS = {"INDIVIDUAL", "FAMILY", "PATRON"}


@bp.route("/memberships", methods=["POST"])
def create_membership():
    _, role = authenticate()
    require_role(role, {"MembershipClerk"})
    body = get_body()
    name = require_string(body, "primary_member_name")
    tier = require_enum(body, "tier", TIERS)
    home_zip = require_string(body, "home_zip")
    party_size = optional_int(body, "party_size", 1)

    # Party-size composition rule (ERR_PARTY_SIZE_INVALID, priority 14).
    if tier == "INDIVIDUAL":
        if party_size != 1:
            raise err(ERR_PARTY_SIZE_INVALID, "INDIVIDUAL membership party_size must be 1")
    else:  # FAMILY or PATRON
        if party_size < 1 or party_size > 6:
            raise err(ERR_PARTY_SIZE_INVALID, "FAMILY/PATRON party_size must be 1..6")

    astc_eligible = tier in ("FAMILY", "PATRON")

    with db.lock:
        rec = new_record(with_version=True)
        rec.update({
            "primary_member_name": name,
            "tier": tier,
            "astc_eligible": astc_eligible,
            "home_zip": home_zip,
            "party_size": party_size,
            "status": "PENDING",
            "activated_at": None,
            "expires_at": None,
            "dues_paid_cents": 0,
            "_activated_at_dt": None,
            "_expires_at_dt": None,
        })
        db.memberships[rec["id"]] = rec
    return success(membership_view(rec), status=201)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    _, role = authenticate()
    require_role(role, {"MembershipClerk", "BoxOfficeOperator"})
    limit, offset = parse_pagination()
    tier = request.args.get("tier")
    status = request.args.get("status")
    with db.lock:
        records = list(db.memberships.values())
        if tier is not None:
            records = [m for m in records if m["tier"] == tier]
        if status is not None:
            records = [m for m in records if m["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [membership_view(m) for m in page]
    return success(data, status=200, pagination=meta)


@bp.route("/memberships/<mid>", methods=["GET"])
def get_one_membership(mid):
    _, role = authenticate()
    require_role(role, {"MembershipClerk", "BoxOfficeOperator", "ProgramCoordinator"})
    with db.lock:
        m = get_membership(mid)
        return success(membership_view(m), status=200)


@bp.route("/memberships/<mid>/activate", methods=["POST"])
def activate_membership(mid):
    _, role = authenticate()
    require_role(role, {"MembershipClerk"})
    body = get_body()
    dues = require_int(body, "dues_cents")
    with db.lock:
        m = get_membership(mid)
        # Activate is defined from PENDING and (renewal) from EXPIRED.
        if m["status"] not in ("PENDING", "EXPIRED"):
            raise err(ERR_INVALID_STATE, "Membership not in an activatable state")
        now = db.clock.now
        expires = db.clock.plus_days(now, 365)
        m["_activated_at_dt"] = now
        m["_expires_at_dt"] = expires
        m["activated_at"] = iso(now)
        m["expires_at"] = iso(expires)
        m["dues_paid_cents"] = m["dues_paid_cents"] + dues
        m["astc_eligible"] = m["tier"] in ("FAMILY", "PATRON")
        m["status"] = "ACTIVE"
        touch(m)
        return success(membership_view(m), status=200)


@bp.route("/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    _, role = authenticate()
    require_role(role, {"MembershipClerk"})
    with db.lock:
        m = get_membership(mid)
        # Cancellation allowed from ACTIVE or PENDING.
        if m["status"] not in ("ACTIVE", "PENDING"):
            raise err(ERR_INVALID_STATE, "Membership not cancellable from its current state")
        m["status"] = "CANCELLED"
        touch(m)
        return success(membership_view(m), status=200)


@bp.route("/memberships/<mid>/astc-status", methods=["GET"])
def astc_status(mid):
    _, role = authenticate()
    require_role(role, {"MembershipClerk", "BoxOfficeOperator"})
    with db.lock:
        m = get_membership(mid)
        view = membership_view(m)
        view["astc_reciprocal_admit"] = astc_reciprocal_admit(m)
        return success(view, status=200)
