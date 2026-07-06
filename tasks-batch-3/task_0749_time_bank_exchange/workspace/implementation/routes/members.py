"""Member CRUD + ledger sub-resource."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_ANON, ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from response import envelope_object, envelope_array
from services import validators, balance, pagination
from services.serializers import member_dto, ledger_entry_dto
from db import parse_iso

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    require_role({ROLE_ANON})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["email", "display_name", "home_neighborhood"])
    email = validators.require_str(payload, "email")
    display_name = validators.require_str(payload, "display_name")
    home = validators.require_str(payload, "home_neighborhood")

    # Uniqueness across active members (all members are "active"; there's no
    # deletion path).
    for m in db.members.values():
        if m["email"] == email:
            raise_err(ERR_INVALID_REQUEST, "email must be unique across active members")

    m = {
        "email": email,
        "display_name": display_name,
        "home_neighborhood": home,
        "trust_tier": "UNVERIFIED",
        "verified_credential_count": 0,
        "completed_exchange_count": 0,
        "chronological_balance_minutes": 0,
        "forward_looking_balance_minutes": 0,
        "lifetime_earned_minutes": 0,
        "lifetime_redeemed_minutes": 0,
        "no_show_strikes": 0,
        "is_suspended": False,
    }
    db.stamp_new(m)
    db.members[m["id"]] = m
    return envelope_object(member_dto(m), status=201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    m = db.members.get(mid)
    if m is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")
    # forward_looking is recomputed at read time (§1.5); refresh but DO NOT bump version.
    balance.recompute_member_snapshot(mid, bump_version=False)
    return envelope_object(member_dto(m), status=200)


@bp.route("/members", methods=["GET"])
def list_members():
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    hood = request.args.get("home_neighborhood")
    tier = request.args.get("trust_tier")
    sus_raw = request.args.get("is_suspended")
    sus = None
    if sus_raw is not None:
        if sus_raw.lower() == "true":
            sus = True
        elif sus_raw.lower() == "false":
            sus = False
        else:
            raise_err(ERR_INVALID_REQUEST, "is_suspended must be true/false")

    items = list(db.members.values())
    if hood is not None:
        items = [m for m in items if m["home_neighborhood"] == hood]
    if tier is not None:
        items = [m for m in items if m["trust_tier"] == tier]
    if sus is not None:
        items = [m for m in items if m["is_suspended"] == sus]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([member_dto(m) for m in window], limit, offset, total)


@bp.route("/members/<mid>/ledger-entries", methods=["GET"])
def list_member_ledger(mid):
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    if db.members.get(mid) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")
    limit, offset = pagination.parse_pagination()
    items = [e for e in db.ledger_entries.values() if e["member_id"] == mid]
    # Ledger entries: sort chronologically by posted_at ASC then created_at ASC.
    ordered = sorted(items, key=lambda e: (parse_iso(e["posted_at"]),
                                           parse_iso(e["created_at"]),
                                           e.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return envelope_array([ledger_entry_dto(e) for e in window], limit, offset, total)
