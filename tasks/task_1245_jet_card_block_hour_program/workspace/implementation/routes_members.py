"""Member endpoints."""

from flask import Blueprint, g

from httpkit import (
    authenticate, ensure_empty_body, err_invalid_request, err_not_found,
    get_body, paginate, require_member_ownership, require_roles,
    respond_object, sorted_items,
)
from serializers import member_json
from services import new_common, touch
from store import db

bp = Blueprint("members", __name__)

TIERS = ["INDIVIDUAL", "FAMILY", "CORPORATE"]


def get_member_or_404(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise err_not_found(f"Member {member_id} does not exist")
    return m


@bp.post("/members")
def create_member():
    data = get_body([
        {"name": "email", "type": "string", "required": True},
        {"name": "full_name", "type": "string", "required": True},
        {"name": "tier", "type": "enum", "values": TIERS, "required": True},
        {"name": "home_base_icao", "type": "string", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    for existing in db.members.values():
        if existing["email"] == data["email"]:
            raise err_invalid_request("email must be unique")
    m = new_common()
    m.update({
        "email": data["email"],
        "full_name": data["full_name"],
        "member_status": "ACTIVE",
        "tier": data["tier"],
        "home_base_icao": data["home_base_icao"],
    })
    db.members[m["id"]] = m
    return respond_object(member_json(m), 201)


@bp.get("/members/<memberId>")
def get_member(memberId):
    authenticate()
    require_roles("Ops", "Member")
    m = get_member_or_404(memberId)
    require_member_ownership(m["id"])
    return respond_object(member_json(m))


@bp.post("/members/<memberId>/suspend")
def suspend_member(memberId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    m = get_member_or_404(memberId)
    m["member_status"] = "SUSPENDED"
    touch(m)
    return respond_object(member_json(m))


# --- FK reverse-reachability read -------------------------------------------

@bp.get("/members/<id>/jet_cards")
def list_member_jet_cards(id):
    from serializers import card_json
    authenticate()
    require_roles("Ops", "Member")
    get_member_or_404(id)
    require_member_ownership(id)
    items = sorted_items(
        c for c in db.cards.values() if c["member_id"] == id)
    return paginate([card_json(c) for c in items])
