"""Ticket tiers, sales and holds (PRD 3.5)."""

from flask import Blueprint

import common
import recompute
import serializers as ser
import store
import validation as v
from envelope import created, list_response, object_response
from errors import ApiError
from store import db, new_entity

bp = Blueprint("tickets", __name__)

HOLD_KINDS = ("COMP", "ARTIST_HOLD", "PRODUCTION_HOLD", "PROMOTER_HOLD")
OPEN_SALES_STATUSES = ("PRE_SALE", "SELLING", "PAUSED")


# ---------------------------------------------------------------------------
# ticket tiers
# ---------------------------------------------------------------------------

@bp.post("/ticket-tiers")
def create_tier():
    common.auth("TalentBuyer")
    body = v.get_body()
    show_id = v.req_str(body, "show_id")
    tier_name = v.req_str(body, "tier_name", max_len=40)
    price = v.req_cents(body, "price_cents", minimum=1)
    allocation = v.req_int(body, "allocation_qty", minimum=1)

    show = common.get_show(show_id)
    venue = common.venue_of(show)
    existing = store.tiers_of_show(show_id)
    if sum(t["allocation_qty"] for t in existing) + allocation > venue["gross_capacity"]:
        raise ApiError("ERR_VENUE_CAPACITY_EXCEEDED",
                       "total allocation exceeds the venue's gross capacity")
    if any(t["tier_name"] == tier_name for t in existing):
        raise ApiError("ERR_DUPLICATE_TIER_NAME",
                       "tier_name must be unique within the show")

    tier = new_entity(
        show_id=show_id,
        tier_name=tier_name,
        price_cents=price,
        allocation_qty=allocation,
        sold_qty=0,
        gross_sold_cents=0,
        comp_qty=0,
        held_qty=0,
        available_qty=allocation,
        price_revision_count=0,
        last_price_cents=None,
        status="DRAFT",
    )
    db.ticket_tiers[tier["id"]] = tier
    recompute.recompute_tier(tier)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return created(ser.ticket_tier_json(tier))


@bp.get("/ticket-tiers/<ticket_tier_id>")
def read_tier(ticket_tier_id):
    common.auth(*common.ALL_ROLES)
    tier = common.get_tier(ticket_tier_id)
    return object_response(ser.ticket_tier_json(tier))


@bp.get("/ticket-tiers")
def list_tiers():
    common.auth(*common.ALL_ROLES)
    show_id = common.filter_fk("show_id", common.get_show)
    status = common.filter_arg("status")
    rows = []
    for tier in db.ticket_tiers.values():
        if show_id is not None and tier["show_id"] != show_id:
            continue
        if status is not None and tier["status"] != status:
            continue
        rows.append(tier)
    page, limit, offset, total = common.listing(rows, ser.ticket_tier_json)
    return list_response(page, limit, offset, total)


@bp.post("/ticket-tiers/<ticket_tier_id>/price-adjustments")
def adjust_price(ticket_tier_id):
    common.auth("TalentBuyer")
    body = v.get_body()
    new_price = v.req_cents(body, "new_price_cents", minimum=1)
    expected_version = v.req_int(body, "expected_show_version")
    v.req_str(body, "reason", max_len=200)

    tier = common.get_tier(ticket_tier_id)
    show = common.show_of_tier(tier)
    common.check_show_version(show, expected_version)
    common.state_guard(tier["status"], ("DRAFT", "ON_SALE", "PAUSED"),
                       common.TERMINAL_TIER)
    common.require(show["sales_status"] != "CLOSED", "ticketing is closed")

    tier["last_price_cents"] = tier["price_cents"]
    tier["price_cents"] = new_price
    tier["price_revision_count"] += 1
    recompute.recompute_tier(tier)
    store.touch(tier)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return object_response(ser.ticket_tier_json(tier))


@bp.post("/ticket-tiers/<ticket_tier_id>/sales")
def record_sale(ticket_tier_id):
    common.auth("TalentBuyer", "VenueOperator")
    body = v.get_body()
    qty = v.req_qty(body, "qty")

    tier = common.get_tier(ticket_tier_id)
    common.state_guard(tier["status"], ("ON_SALE",), common.TERMINAL_TIER)
    show = common.show_of_tier(tier)
    common.require(show["sales_status"] == "SELLING", "the show is not selling")
    if qty > tier["available_qty"]:
        raise ApiError("ERR_INSUFFICIENT_TIER_INVENTORY",
                       "qty exceeds the tier's available inventory")

    tier["sold_qty"] += qty
    tier["gross_sold_cents"] += qty * tier["price_cents"]
    recompute.recompute_tier(tier)
    store.touch(tier)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return object_response(ser.ticket_tier_json(tier))


# ---------------------------------------------------------------------------
# ticket holds
# ---------------------------------------------------------------------------

def _require_hold_owner(show, kind, user_id, role):
    if role == "ArtistRep":
        if kind != "ARTIST_HOLD" or show["artist_id"] != user_id:
            common.not_owner()
    elif role == "VenueOperator":
        if kind != "PRODUCTION_HOLD" or show["venue_id"] != user_id:
            common.not_owner()


@bp.post("/ticket-holds")
def create_hold():
    user_id, role = common.auth("TalentBuyer", "ArtistRep", "VenueOperator")
    body = v.get_body()
    tier_id = v.req_str(body, "ticket_tier_id")
    kind = v.req_enum(body, "kind", HOLD_KINDS)
    qty = v.req_qty(body, "qty")
    holder = v.req_str(body, "holder", max_len=120)
    expires_at = v.opt_ts(body, "expires_at")

    tier = common.get_tier(tier_id)
    show = common.show_of_tier(tier)
    _require_hold_owner(show, kind, user_id, role)
    common.require(tier["status"] != "CLOSED", "the tier is closed")
    common.require(show["sales_status"] != "CLOSED", "ticketing is closed")

    if kind == "COMP":
        allowance = recompute.comp_allowance(show["id"])
        if show["comp_tickets_issued"] + qty > allowance:
            raise ApiError("ERR_COMP_ALLOWANCE_EXCEEDED",
                           "the show's comp allowance is exhausted")
    if qty > tier["available_qty"]:
        raise ApiError("ERR_INSUFFICIENT_TIER_INVENTORY",
                       "qty exceeds the tier's available inventory")

    hold = new_entity(
        ticket_tier_id=tier_id,
        kind=kind,
        qty=qty,
        holder=holder,
        expires_at=expires_at,
        status="HELD",
        released_by_user_id=None,
    )
    db.ticket_holds[hold["id"]] = hold
    recompute.recompute_tier(tier)
    store.touch(tier)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return created(ser.ticket_hold_json(hold))


@bp.get("/ticket-holds/<ticket_hold_id>")
def read_hold(ticket_hold_id):
    common.auth(*common.ALL_ROLES)
    hold = common.get_hold(ticket_hold_id)
    return object_response(ser.ticket_hold_json(hold))


@bp.get("/ticket-holds")
def list_holds():
    common.auth(*common.ALL_ROLES)
    tier_id = common.filter_fk("ticket_tier_id", common.get_tier)
    kind = common.filter_arg("kind")
    status = common.filter_arg("status")
    rows = []
    for hold in db.ticket_holds.values():
        if tier_id is not None and hold["ticket_tier_id"] != tier_id:
            continue
        if kind is not None and hold["kind"] != kind:
            continue
        if status is not None and hold["status"] != status:
            continue
        rows.append(hold)
    page, limit, offset, total = common.listing(rows, ser.ticket_hold_json)
    return list_response(page, limit, offset, total)


@bp.post("/ticket-holds/<ticket_hold_id>/release")
def release_hold(ticket_hold_id):
    user_id, role = common.auth("TalentBuyer", "ArtistRep", "VenueOperator")
    v.get_body()
    hold = common.get_hold(ticket_hold_id)
    tier = common.get_tier(hold["ticket_tier_id"])
    show = common.show_of_tier(tier)
    _require_hold_owner(show, hold["kind"], user_id, role)
    common.state_guard(hold["status"], ("HELD",), common.TERMINAL_HOLD)
    common.require(show["sales_status"] != "CLOSED", "ticketing is closed")

    hold["status"] = "RELEASED"
    hold["released_by_user_id"] = user_id
    store.touch(hold)
    recompute.recompute_tier(tier)
    store.touch(tier)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return object_response(ser.ticket_hold_json(hold))


@bp.post("/ticket-holds/<ticket_hold_id>/convert-to-comp")
def convert_hold(ticket_hold_id):
    user_id, _role = common.auth("TalentBuyer")
    v.get_body()
    hold = common.get_hold(ticket_hold_id)
    tier = common.get_tier(hold["ticket_tier_id"])
    show = common.show_of_tier(tier)
    common.state_guard(hold["status"], ("HELD",), common.TERMINAL_HOLD)
    common.require(hold["kind"] != "COMP", "the hold is already a comp hold")
    common.require(show["sales_status"] in OPEN_SALES_STATUSES,
                   "ticketing is closed")

    allowance = recompute.comp_allowance(show["id"])
    if show["comp_tickets_issued"] + hold["qty"] > allowance:
        raise ApiError("ERR_COMP_ALLOWANCE_EXCEEDED",
                       "the show's comp allowance is exhausted")

    hold["kind"] = "COMP"
    hold["status"] = "CONVERTED"
    hold["released_by_user_id"] = user_id
    store.touch(hold)
    recompute.recompute_tier(tier)
    store.touch(tier)
    recompute.cascade(show, bump_show=True, bump_market=False)
    return object_response(ser.ticket_hold_json(hold))
