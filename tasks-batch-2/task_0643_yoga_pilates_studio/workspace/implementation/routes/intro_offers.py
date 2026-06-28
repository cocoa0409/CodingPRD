"""IntroOffer endpoints + redeemed-entitlement reverse read."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import authenticate, require_roles
from models import make_intro_offer, serialize
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate,
                     require_str, require_int, find_or_404)

bp = Blueprint("intro_offers", __name__)


@bp.post("/intro-offers")
def create_intro_offer():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    name = require_str(body, "name")
    price_cents = require_int(body, "price_cents", minimum=0)
    credits_total = require_int(body, "credits_total", minimum=-1)
    window_days = require_int(body, "window_days", minimum=1)
    offer = make_intro_offer(name, price_cents, credits_total, window_days)
    store.intro_offers[offer["id"]] = offer
    return success(serialize(offer), status=201)


@bp.get("/intro-offers/<oid>")
def get_intro_offer(oid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    offer = find_or_404(store.intro_offers, oid, "IntroOffer")
    return success(serialize(offer))


@bp.get("/intro-offers")
def list_intro_offers():
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(store.intro_offers.values())
    if status is not None:
        items = [o for o in items if o["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(o) for o in window], 200, limit, offset, total)


@bp.get("/intro-offers/<oid>/entitlements")
def intro_offer_entitlements(oid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    find_or_404(store.intro_offers, oid, "IntroOffer")
    limit, offset = parse_pagination()
    items = [e for e in store.entitlements.values() if e.get("intro_offer_id") == oid]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(e) for e in window], 200, limit, offset, total)
