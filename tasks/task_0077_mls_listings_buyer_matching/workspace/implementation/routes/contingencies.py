"""Contingency get/list/resolve/waive/fail."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import body, get_or_404, require_int
from middleware import authenticate
from response import ok, ok_list, parse_pagination, paginate
from serializers import serialize_contingency
from services.money import financing_passes
from services.state import (touch, offer_contingencies,
                            bubble_to_pending_if_ready, fail_contingency_cascade)

bp = Blueprint("contingencies", __name__)


@bp.get("/contingencies/<cid>")
def get_contingency(cid):
    rec = get_or_404(db.contingencies, cid)
    return ok(serialize_contingency(rec))


@bp.get("/offers/<oid>/contingencies")
def list_offer_contingencies(oid):
    get_or_404(db.offers, oid)
    limit, offset = parse_pagination()
    rows = [c for c in db.contingencies.values() if c["offer_id"] == oid]
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind:
        rows = [c for c in rows if c["kind"] == kind]
    if status:
        rows = [c for c in rows if c["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_contingency(c) for c in page], total, limit, offset)


def _load_context(cid):
    cont = get_or_404(db.contingencies, cid)
    offer = db.offers.get(cont["offer_id"])
    listing = db.listings.get(offer["listing_id"]) if offer else None
    return cont, offer, listing


def _guard_buyer_and_state(uid, cont, offer, listing):
    if uid != offer["buyer_agent_id"]:
        raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")
    if cont["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Contingency not PENDING")
    if not listing or listing["status"] != "UNDER_CONTRACT":
        raise err("ERR_INVALID_STATE", "Listing not UNDER_CONTRACT")


@bp.post("/contingencies/<cid>/resolve")
def resolve_contingency(cid):
    role, uid = authenticate({"BuyerAgent"})
    cont, offer, listing = _load_context(cid)
    data = body()
    _guard_buyer_and_state(uid, cont, offer, listing)

    kind = cont["kind"]
    if kind == "INSPECTION":
        passed = True
    elif kind == "APPRAISAL":
        appraised = require_int(data, "appraised_value_cents", required=False, default=0, min_value=0)
        cont["appraised_value_cents"] = appraised
        passed = appraised >= offer["effective_price_cents"]
    elif kind == "FINANCING":
        buyer = db.buyers.get(offer["buyer_id"])
        passed = financing_passes(buyer, offer["effective_price_cents"])
    else:
        passed = True

    if passed:
        cont["status"] = "SATISFIED"
        touch(cont)
        bubble_to_pending_if_ready(listing, offer)
    else:
        cont["status"] = "FAILED"
        touch(cont)
        fail_contingency_cascade(listing, offer)
    return ok(serialize_contingency(cont))


@bp.post("/contingencies/<cid>/waive")
def waive_contingency(cid):
    role, uid = authenticate({"BuyerAgent"})
    cont, offer, listing = _load_context(cid)
    _guard_buyer_and_state(uid, cont, offer, listing)
    cont["status"] = "WAIVED"
    touch(cont)
    bubble_to_pending_if_ready(listing, offer)
    return ok(serialize_contingency(cont))


@bp.post("/contingencies/<cid>/fail")
def fail_contingency(cid):
    role, uid = authenticate({"BuyerAgent"})
    cont, offer, listing = _load_context(cid)
    _guard_buyer_and_state(uid, cont, offer, listing)
    cont["status"] = "FAILED"
    touch(cont)
    fail_contingency_cascade(listing, offer)
    return ok(serialize_contingency(cont))
