"""Offers and Deals: the negotiation loop and the accepted snapshot (PRD 3.3)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, g, request

import store
from domain import DEPOSIT_LEAD_DAYS, rhu, dec
from envelope import created, ok
from errors import (already_terminal, biz, invalid_state, not_found,
                    stale_version)
from helpers import (body, caller_offer_side, filter_eq, get_child, get_show,
                     list_response, lookup, opt_int, opt_num,
                     req_enum, req_expected_show_version, require_roles,
                     ser_deal, ser_offer)

bp = Blueprint("negotiation", __name__)

READ_ROLES = ("VenueManager", "BookingAgent", "Promoter")
DEAL_READ_ROLES = ("VenueManager", "BookingAgent", "Promoter", "Accountant")
DEAL_KINDS = ("FLAT_GUARANTEE", "DOOR_SPLIT", "VERSUS")
TERMINAL_OFFERS = {"ACCEPTED", "REJECTED", "WITHDRAWN", "SUPERSEDED"}


def _validate_deal_terms(b):
    """Rule 15: kind-required fields and split ranges. Returns a terms dict."""
    kind = req_enum(b, "deal_kind", DEAL_KINDS)
    guarantee = opt_int(b, "guarantee_cents")
    split = opt_num(b, "artist_split_pct")
    threshold = opt_int(b, "versus_threshold_cents")
    expense_budget = opt_int(b, "expense_budget_cents")
    support_budget = opt_int(b, "support_budget_cents")
    bar_split = opt_num(b, "bar_split_pct")
    merch_split = opt_num(b, "merch_split_pct")

    def terms_fail(msg):
        return biz("ERR_INVALID_DEAL_TERMS", msg)

    if kind in ("FLAT_GUARANTEE", "VERSUS"):
        if guarantee is None or guarantee < 0:
            raise terms_fail("guarantee_cents (>= 0) is required for %s" % kind)
    if kind in ("DOOR_SPLIT", "VERSUS"):
        if split is None:
            raise terms_fail("artist_split_pct is required for %s" % kind)
    if kind == "VERSUS":
        if threshold is None or threshold < 0:
            raise terms_fail("versus_threshold_cents (>= 0) is required for VERSUS")
    if split is not None and not (0.0 <= split <= 1.0):
        raise terms_fail("artist_split_pct must be within [0.0, 1.0]")
    if bar_split is None or not (0.0 <= bar_split <= 0.25):
        raise terms_fail("bar_split_pct must be within [0.0, 0.25]")
    if merch_split is None or not (0.0 <= merch_split <= 0.30):
        raise terms_fail("merch_split_pct must be within [0.0, 0.30]")
    if expense_budget is None or expense_budget < 0:
        raise terms_fail("expense_budget_cents (>= 0) is required")
    if support_budget is None or support_budget < 0:
        raise terms_fail("support_budget_cents (>= 0) is required")
    return {
        "deal_kind": kind,
        "guarantee_cents": guarantee,
        "artist_split_pct": split,
        "versus_threshold_cents": threshold,
        "expense_budget_cents": expense_budget,
        "support_budget_cents": support_budget,
        "bar_split_pct": bar_split,
        "merch_split_pct": merch_split,
    }


def _check_guarantee_floor(show, terms):
    """Rule 16 (after rule 15): guarantee-bearing kinds must meet the floor."""
    if terms["deal_kind"] in ("FLAT_GUARANTEE", "VERSUS"):
        artist = store.artists.get(show["artist_id"])
        floor = artist["guarantee_floor_cents"] if artist else 0
        if (terms["guarantee_cents"] or 0) < floor:
            raise biz("ERR_GUARANTEE_BELOW_FLOOR",
                      "guarantee_cents is below the artist's guarantee floor")


def _new_offer(show, terms, proposer_role, round_number, supersedes):
    o = store.new_common({
        "show_id": show["id"],
        "round_number": round_number,
        "proposed_by_role": proposer_role,
        "status": "PENDING",
        "supersedes_offer_id": supersedes,
        **terms,
    })
    store.offers[o["id"]] = o
    return o


@bp.get("/offers/<oid>")
def get_offer_top(oid):
    require_roles(*READ_ROLES)
    return ok(ser_offer(lookup(store.offers, oid, "Offer")))


@bp.get("/offers")
def list_offers_top():
    require_roles(*READ_ROLES)
    items = list(store.offers.values())
    items = filter_eq(items, "show_id", request.args.get("show_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    items = filter_eq(items, "supersedes_offer_id", request.args.get("supersedes_offer_id"))
    return list_response(items, ser_offer)


@bp.post("/shows/<sid>/offers")
def create_offer(sid):
    require_roles("BookingAgent", "VenueManager")
    show = get_show(sid)
    b = body()
    terms = _validate_deal_terms(b)
    _check_guarantee_floor(show, terms)
    rounds = [o["round_number"] for o in store.offers.values() if o["show_id"] == show["id"]]
    o = _new_offer(show, terms, caller_offer_side(), (max(rounds) + 1) if rounds else 1, None)
    return created(ser_offer(o))


@bp.get("/shows/<sid>/offers")
def list_offers(sid):
    require_roles(*READ_ROLES)
    show = get_show(sid)
    items = [o for o in store.offers.values() if o["show_id"] == show["id"]]
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items, ser_offer)


@bp.get("/shows/<sid>/offers/<oid>")
def get_offer(sid, oid):
    require_roles(*READ_ROLES)
    show = get_show(sid)
    return ok(ser_offer(get_child(store.offers, show, oid, "Offer")))


def _offer_state_check(offer, action):
    if offer["status"] != "PENDING":
        if offer["status"] in TERMINAL_OFFERS:
            raise already_terminal("Offer is already in a terminal state")
        raise invalid_state("Only a PENDING offer can be %s" % action)


def _self_negotiation_check(offer):
    if caller_offer_side() == offer["proposed_by_role"]:
        raise biz("ERR_SELF_NEGOTIATION",
                  "The side that proposed an offer cannot answer it")


@bp.post("/shows/<sid>/offers/<oid>/counter")
def counter_offer(sid, oid):
    require_roles("BookingAgent", "VenueManager")
    show = get_show(sid)
    offer = get_child(store.offers, show, oid, "Offer")
    _offer_state_check(offer, "countered")
    if show["status"] not in ("HOLD_PENDING", "CONFIRMED"):
        if show["status"] in ("SETTLED", "CANCELLED"):
            raise already_terminal("Show is already in a terminal state")
        raise invalid_state("Offers can only be countered while the show is HOLD_PENDING or CONFIRMED")
    b = body()
    terms = _validate_deal_terms(b)
    _check_guarantee_floor(show, terms)
    _self_negotiation_check(offer)
    offer["status"] = "COUNTERED"
    store.touch(offer)
    new_offer = _new_offer(show, terms, caller_offer_side(), offer["round_number"] + 1, offer["id"])
    return created(ser_offer(new_offer))


@bp.post("/shows/<sid>/offers/<oid>/accept")
def accept_offer(sid, oid):
    require_roles("BookingAgent", "VenueManager")
    show = get_show(sid)
    offer = get_child(store.offers, show, oid, "Offer")
    _offer_state_check(offer, "accepted")
    if show["status"] != "CONFIRMED":
        if show["status"] in ("SETTLED", "CANCELLED"):
            raise already_terminal("Show is already in a terminal state")
        raise invalid_state("Offers can only be accepted while the show is CONFIRMED")
    # OCC (rule 6)
    expected = req_expected_show_version(body())
    if expected != show["version"]:
        raise stale_version()
    # Rule 20: no self-negotiation
    _self_negotiation_check(offer)

    offer["status"] = "ACCEPTED"
    store.touch(offer)
    deal = store.new_common({
        "show_id": show["id"],
        "offer_id": offer["id"],
        "deal_kind": offer["deal_kind"],
        "guarantee_cents": offer.get("guarantee_cents"),
        "artist_split_pct": offer.get("artist_split_pct"),
        "versus_threshold_cents": offer.get("versus_threshold_cents"),
        "expense_budget_cents": offer.get("expense_budget_cents"),
        "support_budget_cents": offer.get("support_budget_cents"),
        "bar_split_pct": offer.get("bar_split_pct"),
        "merch_split_pct": offer.get("merch_split_pct"),
        "status": "ACTIVE",
    })
    store.deals[deal["id"]] = deal
    show["deal_id"] = deal["id"]

    # Deposit economics, fixed exactly once at acceptance
    artist = store.artists.get(show["artist_id"])
    deposit_pct = artist["deposit_pct"] if artist else 0
    guarantee = offer.get("guarantee_cents") or 0
    show["deposit_required_cents"] = rhu(Decimal(guarantee) * dec(deposit_pct))
    due_date = show["_show_date_obj"] - timedelta(days=DEPOSIT_LEAD_DAYS)
    show["deposit_due_by_utc"] = datetime(due_date.year, due_date.month, due_date.day,
                                          tzinfo=timezone.utc)
    # Sweep other open offers to SUPERSEDED
    for o in store.offers.values():
        if o["show_id"] == show["id"] and o["id"] != offer["id"] \
                and o["status"] in ("PENDING", "COUNTERED"):
            o["status"] = "SUPERSEDED"
            store.touch(o)
    store.bump_show(show)
    return ok(ser_deal(deal))


@bp.post("/shows/<sid>/offers/<oid>/reject")
def reject_offer(sid, oid):
    require_roles("BookingAgent", "VenueManager")
    show = get_show(sid)
    offer = get_child(store.offers, show, oid, "Offer")
    _offer_state_check(offer, "rejected")
    _self_negotiation_check(offer)
    offer["status"] = "REJECTED"
    store.touch(offer)
    return ok(ser_offer(offer))


@bp.post("/shows/<sid>/offers/<oid>/withdraw")
def withdraw_offer(sid, oid):
    require_roles("BookingAgent", "VenueManager")
    show = get_show(sid)
    offer = get_child(store.offers, show, oid, "Offer")
    _offer_state_check(offer, "withdrawn")
    # Only the proposing side may withdraw
    if caller_offer_side() != offer["proposed_by_role"]:
        from errors import forbidden
        raise forbidden("Only the side that proposed the offer may withdraw it")
    offer["status"] = "WITHDRAWN"
    store.touch(offer)
    return ok(ser_offer(offer))


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------
@bp.get("/shows/<sid>/deal")
def get_show_deal(sid):
    require_roles(*DEAL_READ_ROLES)
    show = get_show(sid)
    deal = store.deals.get(show["deal_id"]) if show.get("deal_id") else None
    if deal is None or deal["status"] != "ACTIVE":
        raise not_found("Show has no ACTIVE deal")
    return ok(ser_deal(deal))


@bp.get("/deals/<did>")
def get_deal(did):
    require_roles(*DEAL_READ_ROLES)
    return ok(ser_deal(lookup(store.deals, did, "Deal")))


@bp.get("/deals")
def list_deals():
    require_roles(*DEAL_READ_ROLES)
    items = list(store.deals.values())
    items = filter_eq(items, "show_id", request.args.get("show_id"))
    items = filter_eq(items, "offer_id", request.args.get("offer_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items, ser_deal)
