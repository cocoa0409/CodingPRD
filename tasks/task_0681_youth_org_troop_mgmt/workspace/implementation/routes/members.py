"""Member endpoints + dues-driven lifecycle (PRD §3.2)."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from errors import err, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import authenticate, require_roles, BOTH_ROLES, LEADER_ONLY
from response import object_response, array_response
from serializers import serialize_member
from util import new_id, iso_now
from routes import helpers as h
from services import recompute

bp = Blueprint("members", __name__)

MEMBER_TYPES = {"YOUTH", "ADULT"}


@bp.post("/troops/<troop_id>/members")
def create_member(troop_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    troop = h.get_or_404(db.troops, troop_id)
    body = h.get_json_body()

    member_type = h.require_enum(body, "member_type", MEMBER_TYPES)
    full_name = h.require_string(body, "full_name")
    birthdate = h.require_string(body, "birthdate")
    # birthdate must be a valid ISO date YYYY-MM-DD (PRD §3.2).
    try:
        datetime.strptime(birthdate, "%Y-%m-%d")
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "birthdate must be ISO date YYYY-MM-DD")

    now = iso_now(datetime.now(timezone.utc))
    member = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "troop_id": troop["id"],
        "member_type": member_type,
        "full_name": full_name,
        "birthdate": birthdate,
        # Youth begins at rank SCOUT; rank only meaningful for youth.
        "rank": "SCOUT",
        "registration_status": "PENDING",
        "dues_paid_cents": 0,
        "_seq": db.next_seq(),
    }
    db.members[member["id"]] = member
    return object_response(serialize_member(member), status=201)


@bp.get("/members/<member_id>")
def get_member(member_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    member = h.get_or_404(db.members, member_id)
    recompute.refresh_member_read(member)
    return object_response(serialize_member(member))


@bp.get("/members")
def list_members():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    troop_id = request.args.get("troop_id")
    member_type = request.args.get("member_type")
    limit, offset = h.parse_pagination()
    rows = [
        m for m in db.members.values()
        if (troop_id is None or m["troop_id"] == troop_id)
        and (member_type is None or m["member_type"] == member_type)
    ]
    rows = h.sort_by_creation(rows)
    for m in rows:
        recompute.refresh_member_read(m)
    page, total = h.paginate(rows, limit, offset)
    return array_response([serialize_member(m) for m in page], limit, offset, total)


def _bump_owning_troop(member):
    troop = db.troops.get(member["troop_id"])
    if troop is not None:
        recompute.recompute_troop_counts(troop, bump=True)


@bp.post("/members/<member_id>/suspend")
def suspend_member(member_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    member = h.get_or_404(db.members, member_id)
    if member["registration_status"] != "REGISTERED":
        raise err(ERR_INVALID_STATE, "suspend only defined from REGISTERED")
    member["registration_status"] = "SUSPENDED"
    h.touch_and_bump(member)
    _bump_owning_troop(member)
    recompute.refresh_member_read(member)
    return object_response(serialize_member(member))


@bp.post("/members/<member_id>/reinstate")
def reinstate_member(member_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    member = h.get_or_404(db.members, member_id)
    if member["registration_status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "reinstate only defined from SUSPENDED")
    member["registration_status"] = "REGISTERED"
    h.touch_and_bump(member)
    _bump_owning_troop(member)
    recompute.refresh_member_read(member)
    return object_response(serialize_member(member))


@bp.post("/members/<member_id>/drop")
def drop_member(member_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    member = h.get_or_404(db.members, member_id)
    # Drop defined from REGISTERED, SUSPENDED, or PENDING (PRD §3.2).
    if member["registration_status"] not in ("REGISTERED", "SUSPENDED", "PENDING"):
        raise err(ERR_INVALID_STATE, "drop not defined from current status")
    member["registration_status"] = "DROPPED"
    # Void every OPEN DuesInvoice belonging to this member (PRD §3.2).
    for inv in db.dues_invoices.values():
        if inv["member_id"] == member["id"] and inv["status"] == "OPEN":
            inv["status"] = "VOID"
            h.touch_and_bump(inv)
    h.touch_and_bump(member)
    _bump_owning_troop(member)
    recompute.refresh_member_read(member)
    return object_response(serialize_member(member))
