"""Member endpoints (PRD §3.2), plus member-scoped ledger-entries and bonus-streak."""
from flask import Blueprint, request

from db import base_common_fields, touch
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.serialize import member_out, ledger_entry_out, bonus_streak_out
from services.streak import _get_or_create_streak
from state import store
from validation import get_json_body, require_string

bp = Blueprint("members", __name__)

ALL_ROLES = ["PlatformAdmin", "ReviewAgent", "FinanceAdmin", "Member"]


@bp.route("/members", methods=["POST"])
def create_member():
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "Member"])
    body = get_json_body()

    email = require_string(body, "email")

    referred_by_member_id = body.get("referred_by_member_id")
    if referred_by_member_id is not None:
        if not isinstance(referred_by_member_id, str) or referred_by_member_id not in store.members:
            raise err("ERR_REFERENCE_NOT_FOUND", "referred_by_member_id does not resolve.")

    m = base_common_fields(store, full=True)
    m.update({
        "email": email,
        "referred_by_member_id": referred_by_member_id,
        "account_status": "ACTIVE",
        "verification_status": "UNVERIFIED",
    })

    # Member self-register ownership: X-User-ID must be the new member's id is not
    # meaningful (the id is server-minted). The PRD ties ownership to member_id on
    # supplied resources; self-register has no pre-existing member_id, so any
    # Member caller may self-register. No ownership constraint applies here.

    store.members[m["id"]] = m

    # Matching referral (by referee_email + referrer) INVITED -> SIGNED_UP.
    if referred_by_member_id is not None:
        _advance_matching_referral(referred_by_member_id, email, m["id"])

    return object_response(store.clock, member_out(store, m), status=201)


def _advance_matching_referral(referrer_id, email, new_member_id):
    """Find an outstanding INVITED referral from this referrer to this email and
    advance it to SIGNED_UP (PRD §3.7)."""
    # No other referral for this email may already be past INVITED.
    for r in store.referrals.values():
        if r["referee_email"] == email and r["status"] in ("SIGNED_UP", "QUALIFIED", "REWARDED"):
            return
    candidates = sorted(
        [
            r for r in store.referrals.values()
            if r["referrer_member_id"] == referrer_id
            and r["referee_email"] == email
            and r["status"] == "INVITED"
        ],
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    if candidates:
        r = candidates[0]
        r["status"] = "SIGNED_UP"
        r["referee_member_id"] = new_member_id
        touch(store, r)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    user_id, role = get_identity()
    require_roles(role, ALL_ROLES)
    m = store.members.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found.")
    if role == "Member" and not member_owns(user_id, mid):
        raise err("ERR_FORBIDDEN", "A member may only read their own record.")
    return object_response(store.clock, member_out(store, m))


@bp.route("/members", methods=["GET"])
def list_members():
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin"])
    items = list(store.members.values())
    referred_by = request.args.get("referred_by_member_id")
    account_status = request.args.get("account_status")
    verification_status = request.args.get("verification_status")
    if referred_by is not None:
        items = [m for m in items if m.get("referred_by_member_id") == referred_by]
    if account_status is not None:
        items = [m for m in items if m["account_status"] == account_status]
    if verification_status is not None:
        items = [m for m in items if m["verification_status"] == verification_status]
    return list_response(items, member_out)


@bp.route("/members/<mid>/verify", methods=["POST"])
def verify_member(mid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    m = store.members.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found.")
    m["verification_status"] = "VERIFIED"
    touch(store, m)
    return object_response(store.clock, member_out(store, m))


@bp.route("/members/<mid>/suspend", methods=["POST"])
def suspend_member(mid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    m = store.members.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found.")
    m["account_status"] = "SUSPENDED"
    touch(store, m)
    return object_response(store.clock, member_out(store, m))


@bp.route("/members/<mid>/reinstate", methods=["POST"])
def reinstate_member(mid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    m = store.members.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found.")
    m["account_status"] = "ACTIVE"
    touch(store, m)
    return object_response(store.clock, member_out(store, m))


@bp.route("/members/<mid>/ledger-entries", methods=["GET"])
def member_ledger_entries(mid):
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    m = store.members.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found.")
    if role == "Member" and not member_owns(user_id, mid):
        raise err("ERR_FORBIDDEN", "A member may only read their own ledger entries.")
    entry_type = request.args.get("entry_type")
    items = [e for e in store.ledger_entries.values() if e["member_id"] == mid]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    return list_response(items, ledger_entry_out)


@bp.route("/members/<mid>/bonus-streak", methods=["GET"])
def member_bonus_streak(mid):
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    m = store.members.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found.")
    if role == "Member" and not member_owns(user_id, mid):
        raise err("ERR_FORBIDDEN", "A member may only read their own bonus streak.")
    streak = _get_or_create_streak(store, mid)
    return object_response(store.clock, bonus_streak_out(store, streak))
