"""Member and CreditPack endpoints (PRD §3.3, §3.8, §3.9)."""
from flask import Blueprint, request

from clock import clock
from constants import ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_ANONYMOUS
from db import db, stamp_new, touch
from errors import (
    err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_OWNERSHIP_VIOLATION,
    ERR_STALE_PACK_VERSION,
)
from middleware import require_auth, require_role
from response import success_object, success_array
from serializers import member_out, credit_pack_out
from services import lookup, validate, paging
from services import packs as pack_svc

bp = Blueprint("members", __name__)


# ---- Member ----
@bp.route("/members/register", methods=["POST"])
def register_member():
    # Open operation (Anonymous). No auth headers required, but if a role header
    # is present it must be Anonymous-capable; per PRD this is the open path.
    body = validate.get_body()
    email = validate.require_str(body, "email")
    full_name = validate.require_str(body, "full_name")
    home_studio_id = validate.require_str(body, "home_studio_id")
    lookup.get_studio(home_studio_id)
    rec = {
        "email": email,
        "full_name": full_name,
        "home_studio_id": home_studio_id,
        "account_status": "ACTIVE",
        "wallet_credit_cents": 0,
    }
    stamp_new(rec)
    db.members[rec["id"]] = rec
    return success_object(member_out(rec), 201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    user_id, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER, ROLE_MEMBER})
    rec = lookup.get_member(member_id)
    if role == ROLE_MEMBER and user_id != member_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only read their own record")
    # Reading recomputes derived counts against the clock (serializer handles it).
    return success_object(member_out(rec), 200)


@bp.route("/members", methods=["GET"])
def list_members():
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    limit, offset = paging.get_pagination()
    home_studio_id = request.args.get("home_studio_id")
    records = [
        m for m in db.members.values()
        if home_studio_id is None or m["home_studio_id"] == home_studio_id
    ]
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([member_out(m) for m in page], limit, offset, total)


@bp.route("/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member(member_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    rec = lookup.get_member(member_id)
    if rec["account_status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Member is not SUSPENDED")
    rec["account_status"] = "ACTIVE"
    touch(rec)
    return success_object(member_out(rec), 200)


# ---- CreditPack ----
@bp.route("/credit-packs", methods=["POST"])
def create_pack():
    user_id, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER, ROLE_MEMBER})
    body = validate.get_body()
    member_id = validate.require_str(body, "member_id")
    kind = validate.require_enum(body, "kind", {"CLASS_PACK", "MEMBERSHIP"})
    purchased_credits = validate.require_int(body, "purchased_credits", minimum=0)
    price_cents = validate.require_int(body, "price_cents", minimum=0)
    expires_at = validate.require_iso(body, "expires_at")
    scope = validate.opt_str(body, "scope", "HOME_ONLY")
    if scope not in ("HOME_ONLY", "MULTI_STUDIO"):
        raise err(ERR_VALIDATION, "scope must be HOME_ONLY or MULTI_STUDIO")
    grant_studio_ids = validate.opt_str_array(body, "grant_studio_ids", [])

    member = lookup.get_member(member_id)
    if role == ROLE_MEMBER and user_id != member_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only buy their own packs")

    rec = {
        "member_id": member_id,
        "kind": kind,
        "purchased_credits": purchased_credits,
        "price_cents": price_cents,
        "consumed_credits": 0,
        "activated_at": clock.now(),
        "expires_at": expires_at,
        "scope": scope,
        "grant_studio_ids": grant_studio_ids if scope == "MULTI_STUDIO" else [],
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.credit_packs[rec["id"]] = rec
    return success_object(credit_pack_out(rec), 201)


@bp.route("/credit-packs/<pack_id>", methods=["GET"])
def get_pack(pack_id):
    user_id, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER, ROLE_MEMBER})
    rec = lookup.get_pack(pack_id)
    if role == ROLE_MEMBER and user_id != rec["member_id"]:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only read their own packs")
    # Lazy expiry on read (PRD §3.11).
    pack_svc.lazy_expire(rec)
    return success_object(credit_pack_out(rec), 200)


@bp.route("/credit-packs", methods=["GET"])
def list_packs():
    user_id, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER, ROLE_MEMBER})
    limit, offset = paging.get_pagination()
    member_id = request.args.get("member_id")
    records = []
    for p in db.credit_packs.values():
        if member_id is not None and p["member_id"] != member_id:
            continue
        if role == ROLE_MEMBER and p["member_id"] != user_id:
            continue
        pack_svc.lazy_expire(p)
        records.append(p)
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([credit_pack_out(p) for p in page], limit, offset, total)


@bp.route("/credit-packs/<pack_id>/refund", methods=["POST"])
def refund_pack(pack_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    rec = lookup.get_pack(pack_id)
    body = validate.get_body()
    expected_version = validate.require_int(body, "expected_pack_version")

    # Lazy expiry observed before refund (affects amount and version base).
    pack_svc.lazy_expire(rec)

    # State precondition: ACTIVE, EXHAUSTED, or EXPIRED, and no BOOKED reservation
    # still charged to this pack (PRD §3.9).
    if rec["status"] not in ("ACTIVE", "EXHAUSTED", "EXPIRED"):
        raise err(ERR_INVALID_STATE, "Pack cannot be refunded in its current state")
    has_hold = any(
        r["credit_pack_id"] == pack_id and r["attendance_status"] == "BOOKED"
        for r in db.reservations.values()
    )
    if has_hold:
        raise err(ERR_INVALID_STATE, "Pack has unresolved BOOKED holds")

    # OCC after state precondition (validation priority: state(5) before OCC(6)).
    if expected_version != rec["version"]:
        raise err(ERR_STALE_PACK_VERSION, "expected_pack_version does not match current version")

    amount = pack_svc.refund_amount(rec)
    member = db.members.get(rec["member_id"])
    if member is not None and amount:
        member["wallet_credit_cents"] += amount
        touch(member)
    rec["status"] = "REFUNDED"
    touch(rec)
    return success_object(credit_pack_out(rec), 200)
