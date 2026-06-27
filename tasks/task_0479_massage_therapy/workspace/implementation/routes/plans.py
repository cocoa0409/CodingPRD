"""Membership plans & commission tiers (PRD §3.1)."""
from flask import Blueprint, request

import db
import helpers as h
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authenticate, require_role

bp = Blueprint("plans", __name__)


@bp.post("/practice/plans")
def create_plan():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    body = h.get_body()

    name = h.as_str(h.require(body, "name"), "name")
    monthly_fee_cents = h.as_int(h.require(body, "monthly_fee_cents"), "monthly_fee_cents", minimum=0)
    included_sessions = h.as_int(h.require(body, "included_sessions"), "included_sessions", minimum=1)
    member_discount_pct = h.opt(body, "member_discount_pct", None)
    if member_discount_pct is None:
        disc = h.as_fraction_pct(0.15, "member_discount_pct")
    else:
        disc = h.as_fraction_pct(member_discount_pct, "member_discount_pct")
    rollover_cap_sessions = h.opt(body, "rollover_cap_sessions", 1)
    rollover_cap_sessions = h.as_int(rollover_cap_sessions, "rollover_cap_sessions", minimum=0)

    # name unique among non-archived plans
    for p in db.membership_plans.values():
        if not p["archived"] and p["name"] == name:
            raise ApiError(*ERR_INVALID_REQUEST, message="name not unique")

    ent = h.new_entity({
        "name": name,
        "monthly_fee_cents": monthly_fee_cents,
        "included_sessions": included_sessions,
        "member_discount_pct": float(disc),
        "rollover_cap_sessions": rollover_cap_sessions,
        "archived": False,
    })
    ent["_disc_frac"] = disc
    db.membership_plans[ent["id"]] = ent
    return response.success(h.public(ent), status=201)


@bp.get("/practice/plans")
def list_plans():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    limit, offset = h.get_pagination()
    include_archived = h.get_bool_flag("include_archived")
    items = [p for p in db.membership_plans.values() if include_archived or not p["archived"]]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(p) for p in page], limit, offset, total)


@bp.get("/practice/plans/<id>")
def get_plan(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    ent = h.resolve(db.membership_plans, id)
    return response.success(h.public(ent))


# --- Commission tiers ---

@bp.post("/practice/commission-tiers")
def create_tier():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    body = h.get_body()

    tier_index = h.as_int(h.require(body, "tier_index"), "tier_index", minimum=0)
    floor_revenue_cents = h.as_int(h.require(body, "floor_revenue_cents"), "floor_revenue_cents", minimum=0)
    commission_pct = h.as_fraction_pct(h.require(body, "commission_pct"), "commission_pct")

    # tier_index unique among non-archived tiers
    for t in db.commission_tiers.values():
        if not t["archived"] and t["tier_index"] == tier_index:
            raise ApiError(*ERR_INVALID_REQUEST, message="tier_index not unique")

    ent = h.new_entity({
        "tier_index": tier_index,
        "floor_revenue_cents": floor_revenue_cents,
        "commission_pct": float(commission_pct),
        "archived": False,
    })
    ent["_pct_frac"] = commission_pct
    db.commission_tiers[ent["id"]] = ent
    return response.success(h.public(ent), status=201)


@bp.get("/practice/commission-tiers")
def list_tiers():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    limit, offset = h.get_pagination()
    include_archived = h.get_bool_flag("include_archived")
    items = [t for t in db.commission_tiers.values() if include_archived or not t["archived"]]
    # default lists present them sorted by tier_index
    ordered = sorted(items, key=lambda t: (t["tier_index"], t.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return response.list_success([h.public(t) for t in window], limit, offset, total)
