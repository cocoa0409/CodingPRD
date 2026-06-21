from flask import Blueprint, request

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_json
from response import created, ok, listing
from services import validate as V
from services.entities import (
    get_venue, get_gift_card, get_gift_card_entry,
    ser_gift_card, ser_gift_card_entry, gift_card_balance, touch,
)

bp = Blueprint("gift_cards", __name__)


@bp.post("/gift-cards")
def create_gift_card():
    require_roles({"VenueManager"})
    body = get_json()
    venue_id = V.req_str(body, "venue_id")
    code = V.req_str(body, "code")
    initial_balance = V.req_int(body, "initial_balance_cents", min_v=1)
    get_venue(venue_id)

    # Code unique within venue, case-insensitive (PRD §3.9).
    lower = code.lower()
    for g in db.gift_cards.values():
        if g["venue_id"] == venue_id and g["code"].lower() == lower:
            raise err(errors.ERR_DUPLICATE_RESOURCE, "Gift card code already exists")

    ts = now_iso()
    gid = new_id()
    gc = {
        "id": gid,
        "venue_id": venue_id,
        "code": code,
        "initial_balance_cents": initial_balance,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.gift_cards[gid] = gc
    return created(ser_gift_card(gc))


@bp.get("/gift-cards/<gift_card_id>")
def read_gift_card(gift_card_id):
    require_roles({"PlatformAdmin", "VenueManager", "Customer"})
    gc = get_gift_card(gift_card_id)
    return ok(ser_gift_card(gc))


@bp.get("/gift-cards")
def list_gift_cards():
    require_roles({"PlatformAdmin", "VenueManager", "Customer"})
    limit, offset = V.parse_pagination()
    venue_id = request.args.get("venue_id")
    rows = list(db.gift_cards.values())
    if venue_id is not None:
        rows = [g for g in rows if g["venue_id"] == venue_id]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_gift_card(g) for g in page], limit, offset, total)


def _append_entry(gift_card_id, entry_type, delta_cents, related_booking_id=None):
    eid = new_id()
    entry = {
        "id": eid,
        "gift_card_id": gift_card_id,
        "related_booking_id": related_booking_id,
        "entry_type": entry_type,
        "delta_cents": delta_cents,
        "created_at": now_iso(),
    }
    db.gift_card_entries[eid] = entry
    return entry


@bp.post("/gift-cards/<gift_card_id>/top-up")
def top_up(gift_card_id):
    require_roles({"VenueManager"})
    gc = get_gift_card(gift_card_id)
    body = get_json()
    amount = V.req_int(body, "amount_cents", min_v=1)
    expected = V.req_int(body, "expected_gift_card_version")
    if gc["status"] == "VOID":
        raise err(errors.ERR_INVALID_STATE, "Gift card is VOID")
    if expected != gc["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale gift card version")
    _append_entry(gift_card_id, "TOPUP", amount, related_booking_id=None)
    # Recompute balance; a topped-up DEPLETED card returns to ACTIVE.
    bal = gift_card_balance(gift_card_id, gc)
    if gc["status"] == "DEPLETED" and bal > 0:
        gc["status"] = "ACTIVE"
    touch(gc)
    return ok(ser_gift_card(gc))


@bp.post("/gift-cards/<gift_card_id>/void")
def void_gift_card(gift_card_id):
    require_roles({"VenueManager"})
    gc = get_gift_card(gift_card_id)
    body = get_json()
    expected = V.req_int(body, "expected_gift_card_version")
    if gc["status"] == "VOID":
        raise err(errors.ERR_INVALID_STATE, "Gift card already VOID")
    # No CONFIRMED booking holding an outstanding SPEND draw against this card.
    for b in db.bookings.values():
        if (b.get("gift_card_id") == gift_card_id
                and b["lifecycle_status"] == "CONFIRMED"
                and b.get("gift_card_applied_cents", 0) > 0):
            raise err(errors.ERR_INVALID_STATE, "Outstanding authorized draw on gift card")
    if expected != gc["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale gift card version")
    gc["status"] = "VOID"
    touch(gc)
    return ok(ser_gift_card(gc))


@bp.get("/gift-card-entries/<entry_id>")
def read_entry(entry_id):
    require_roles({"PlatformAdmin", "VenueManager", "Customer"})
    entry = get_gift_card_entry(entry_id)
    return ok(ser_gift_card_entry(entry))


@bp.get("/gift-card-entries")
def list_entries():
    require_roles({"PlatformAdmin", "VenueManager", "Customer"})
    limit, offset = V.parse_pagination()
    gift_card_id = request.args.get("gift_card_id")
    related_booking_id = request.args.get("related_booking_id")
    rows = list(db.gift_card_entries.values())
    if gift_card_id is not None:
        rows = [e for e in rows if e["gift_card_id"] == gift_card_id]
    if related_booking_id is not None:
        rows = [e for e in rows if e.get("related_booking_id") == related_booking_id]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_gift_card_entry(e) for e in page], limit, offset, total)
