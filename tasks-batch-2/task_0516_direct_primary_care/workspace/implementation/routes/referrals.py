"""Specialist Referral endpoints (PRD §3.11)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from clock import clock
from middleware import authenticate, require_roles
from routes.helpers import get_or_404
from services.domain import REFERRAL_AUTH_VALID_DAYS

bp = Blueprint("referrals", __name__)


@bp.route("/referrals", methods=["POST"])
def create_referral():
    caller = authenticate()
    require_roles(caller, {"Provider"})
    data = validate.body()

    member_id = validate.require(data, "member_id", str)
    origin_visit_id = validate.require(data, "origin_visit_id", str)
    specialty = validate.require(data, "specialty", str)

    member = get_or_404("member", member_id)
    get_or_404("visit", origin_visit_id)
    if caller.role == "Provider" and member.get("assigned_provider_id") != caller.user_id:
        raise errors.forbidden("Provider does not own this member.")

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["member_id"] = member_id
    e["origin_visit_id"] = origin_visit_id
    e["specialty"] = specialty
    e["referral_status"] = "REQUESTED"
    e["authorized_at"] = None
    e["expires_at"] = None
    db.referrals[e["id"]] = e
    return response.object_response(serialize.referral(e), 201)


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    e = get_or_404("referral", rid)
    _read_ownership(caller, e)
    return response.object_response(serialize.referral(e), 200)


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    limit, offset = validate.pagination()
    member_id = request.args.get("member_id")
    origin_visit_id = request.args.get("origin_visit_id")
    referral_status = request.args.get("referral_status")

    rows = list(db.referrals.values())
    if caller.role == "Member":
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    elif caller.role == "Provider":
        rows = [r for r in rows
                if db.members.get(r["member_id"], {}).get("assigned_provider_id") == caller.user_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if origin_visit_id is not None:
        rows = [r for r in rows if r["origin_visit_id"] == origin_visit_id]
    if referral_status is not None:
        rows = [r for r in rows if r["referral_status"] == referral_status]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.referral(r) for r in page], limit, offset, total, 200
    )


@bp.route("/referrals/<rid>/authorize", methods=["POST"])
def authorize_referral(rid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("referral", rid)
    _provider_owns(caller, e)

    if e["referral_status"] != "REQUESTED":
        raise errors.invalid_state("Referral is not REQUESTED.")
    # Cross-entity (priority 7): owner ACTIVE.
    member = db.members[e["member_id"]]
    if member["membership_status"] != "ACTIVE":
        raise errors.member_not_eligible("Only active members get authorizations.")

    now = clock.now()
    e["authorized_at"] = now
    e["expires_at"] = now + timedelta(days=REFERRAL_AUTH_VALID_DAYS)
    e["referral_status"] = "AUTHORIZED"
    db.touch(e)
    return response.object_response(serialize.referral(e), 200)


@bp.route("/referrals/<rid>/deny", methods=["POST"])
def deny_referral(rid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("referral", rid)
    _provider_owns(caller, e)

    if e["referral_status"] != "REQUESTED":
        raise errors.invalid_state("Referral is not REQUESTED.")
    e["referral_status"] = "DENIED"
    db.touch(e)
    return response.object_response(serialize.referral(e), 200)


@bp.route("/referrals/<rid>/send", methods=["POST"])
def send_referral(rid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("referral", rid)
    _provider_owns(caller, e)

    if e["referral_status"] != "AUTHORIZED":
        raise errors.invalid_state("Referral is not AUTHORIZED.")
    # Business (priority 14): may only send before expires_at.
    if clock.now() >= e["expires_at"]:
        raise errors.referral_expired("Referral has expired.")
    e["referral_status"] = "SENT"
    db.touch(e)
    return response.object_response(serialize.referral(e), 200)


def _read_ownership(caller, ref):
    if caller.role == "Member" and caller.user_id != ref["member_id"]:
        raise errors.forbidden("Member does not own this referral.")
    if caller.role == "Provider":
        _provider_owns(caller, ref)


def _provider_owns(caller, ref):
    if caller.role == "Provider":
        member = db.members.get(ref["member_id"])
        if member is None or member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this referral.")
