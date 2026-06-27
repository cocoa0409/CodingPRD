"""Recital / SeatAssignment routes (PRD 3.8). OCC on seat holds (PRD 2.8)."""
from flask import Blueprint, request

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (lookup, optional_int, paginate, parse_iso_datetime,
                     require_fields, require_int, require_str, sort_by_created)
from middleware import authenticate, get_json, require_owner
from response import success
from services.billing import add_fee_line, credit_family
from views import public, public_list

bp = Blueprint("recitals", __name__)


# --------------------------------------------------------------------------
# Recital lifecycle helpers
# --------------------------------------------------------------------------
def recompute_seats_sold(recital):
    count = sum(
        1 for s in db.seats.values()
        if s["recital_id"] == recital["id"] and s["status"] in {"HELD", "PURCHASED"}
    )
    if recital["seats_sold"] != count:
        recital["seats_sold"] = count
        touch(recital)


def _maybe_sold_out(recital):
    if recital["status"] == "ON_SALE" and recital["seats_sold"] >= recital["total_seats"]:
        recital["status"] = "SOLD_OUT"
        touch(recital)


def _maybe_on_sale(recital):
    if recital["status"] == "SOLD_OUT" and recital["seats_sold"] < recital["total_seats"]:
        recital["status"] = "ON_SALE"
        touch(recital)


def _recompute_family_allotment(recital, family_id):
    """Per PRD ticket_pricing_allotment: the earliest free_tickets_per_family of
    the family's HELD/PURCHASED seats (created_at order) are complimentary."""
    seats = [
        s for s in db.seats.values()
        if s["recital_id"] == recital["id"] and s["family_id"] == family_id
        and s["status"] in {"HELD", "PURCHASED"}
    ]
    seats.sort(key=lambda s: (s["created_at"], s["_seq"]))
    free = recital["free_tickets_per_family"]
    for idx, s in enumerate(seats):
        comp = idx < free
        price = 0 if comp else recital["ticket_price_cents"]
        if s["is_complimentary"] != comp or s["price_cents"] != price:
            s["is_complimentary"] = comp
            s["price_cents"] = price
            touch(s)


@bp.route("/terms/<tid>/recitals", methods=["POST"])
def create_recital(tid):
    authenticate({"StudioAdmin"})
    term = lookup(db.terms, tid)
    body = get_json()
    require_fields(body, ["name", "show_datetime", "total_seats", "ticket_price_cents"])
    name = require_str(body, "name")
    show_dt = parse_iso_datetime(body["show_datetime"])
    total_seats = require_int(body, "total_seats", lo=1)
    ticket_price = require_int(body, "ticket_price_cents", lo=0)
    free = optional_int(body, "free_tickets_per_family", default=0, lo=0)
    recital = {
        "id": new_id(),
        "term_id": term["id"],
        "name": name,
        "show_datetime": body["show_datetime"],
        "total_seats": total_seats,
        "ticket_price_cents": ticket_price,
        "free_tickets_per_family": free,
        "seats_sold": 0,
        "status": "ANNOUNCED",
        **common_fields(),
    }
    db.recitals[recital["id"]] = recital
    return success(public(recital), status=201)


@bp.route("/terms/<tid>/recitals", methods=["GET"])
def list_term_recitals(tid):
    authenticate({"StudioAdmin", "Parent"})
    term = lookup(db.terms, tid)
    items = [r for r in db.recitals.values() if r["term_id"] == term["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/recitals/<rid>", methods=["GET"])
def get_recital(rid):
    authenticate({"StudioAdmin", "Parent"})
    recital = lookup(db.recitals, rid)
    return success(public(recital), status=200)


@bp.route("/recitals/<rid>/open-sales", methods=["POST"])
def open_sales(rid):
    authenticate({"StudioAdmin"})
    recital = lookup(db.recitals, rid)
    if recital["status"] != "ANNOUNCED":
        raise err("ERR_INVALID_STATE", "Recital is not ANNOUNCED.")
    term = db.terms.get(recital["term_id"])
    if term is None or term["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Parent term is not OPEN.")
    if recital["total_seats"] < 1:
        raise err("ERR_INVALID_STATE", "Recital has no seats.")
    recital["status"] = "ON_SALE"
    touch(recital)
    return success(public(recital), status=200)


@bp.route("/recitals/<rid>/complete", methods=["POST"])
def complete_recital(rid):
    authenticate({"StudioAdmin"})
    recital = lookup(db.recitals, rid)
    if recital["status"] not in {"ON_SALE", "SOLD_OUT"}:
        raise err("ERR_INVALID_STATE", "Recital cannot be completed.")
    show_dt = parse_iso_datetime(recital["show_datetime"])
    if db.clock < show_dt:
        raise err("ERR_INVALID_STATE", "Clock has not reached show_datetime.")
    # Release all HELD seats; PURCHASED retained.
    for s in db.seats.values():
        if s["recital_id"] == recital["id"] and s["status"] == "HELD":
            s["status"] = "RELEASED"
            touch(s)
    recital["status"] = "COMPLETED"
    recompute_seats_sold(recital)
    touch(recital)
    return success(public(recital), status=200)


@bp.route("/recitals/<rid>/seats", methods=["POST"])
def hold_seat(rid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    recital = lookup(db.recitals, rid)
    body = get_json()
    require_fields(body, ["family_id", "seat_label", "expected_recital_version"])
    family = lookup(db.families, body["family_id"])
    require_owner(role, user_id, family["id"])
    seat_label = require_str(body, "seat_label")
    expected = require_int(body, "expected_recital_version")

    # State: holds are only allowed while the recital can sell (ON_SALE/SOLD_OUT).
    if recital["status"] not in {"ON_SALE", "SOLD_OUT"}:
        raise err("ERR_INVALID_STATE", "Recital is not on sale.")

    # OCC (priority 6) on the recital version.
    if expected != recital["version"]:
        raise err("ERR_STALE_VERSION", "Recital version mismatch.")

    # Seat label unique among non-RELEASED seats; sold-out gate.
    for s in db.seats.values():
        if s["recital_id"] == recital["id"] and s["status"] != "RELEASED" \
                and s["seat_label"] == seat_label:
            raise err("ERR_RECITAL_SOLD_OUT", "Seat label already taken.")
    if recital["seats_sold"] >= recital["total_seats"]:
        raise err("ERR_RECITAL_SOLD_OUT", "Recital is sold out.")

    # Ticket allotment: count the family's existing HELD/PURCHASED seats.
    existing = sum(
        1 for s in db.seats.values()
        if s["recital_id"] == recital["id"] and s["family_id"] == family["id"]
        and s["status"] in {"HELD", "PURCHASED"}
    )
    if existing < recital["free_tickets_per_family"]:
        comp = True
        price = 0
    else:
        comp = False
        price = recital["ticket_price_cents"]

    seat = {
        "id": new_id(),
        "recital_id": recital["id"],
        "family_id": family["id"],
        "seat_label": seat_label,
        "is_complimentary": comp,
        "price_cents": price,
        "status": "HELD",
        **common_fields(),
    }
    db.seats[seat["id"]] = seat
    recital["seats_sold"] += 1
    touch(recital)  # successful hold bumps the recital version by one
    _maybe_sold_out(recital)
    return success(public(seat), status=201)


@bp.route("/recitals/<rid>/seats", methods=["GET"])
def list_recital_seats(rid):
    authenticate({"StudioAdmin", "Parent"})
    recital = lookup(db.recitals, rid)
    items = [s for s in db.seats.values() if s["recital_id"] == recital["id"]]
    fam = request.args.get("family_id")
    if fam is not None:
        items = [s for s in items if s["family_id"] == fam]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


# --------------------------------------------------------------------------
# Seats (top-level)
# --------------------------------------------------------------------------
@bp.route("/seats/<sid>", methods=["GET"])
def get_seat(sid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    seat = lookup(db.seats, sid)
    require_owner(role, user_id, seat["family_id"])
    return success(public(seat), status=200)


@bp.route("/seats", methods=["GET"])
def list_seats():
    authenticate({"StudioAdmin", "Parent"})
    items = list(db.seats.values())
    for key in ("family_id", "recital_id"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s[key] == val]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/seats/<sid>/purchase", methods=["POST"])
def purchase_seat(sid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    seat = lookup(db.seats, sid)
    require_owner(role, user_id, seat["family_id"])
    if seat["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Seat is not HELD.")
    recital = db.recitals.get(seat["recital_id"])
    if recital is None or recital["status"] not in {"ON_SALE", "SOLD_OUT"}:
        raise err("ERR_INVALID_STATE", "Recital is not on sale.")
    seat["status"] = "PURCHASED"
    touch(seat)
    # Charge the pinned price (complimentary = 0): fold into family's OPEN invoice.
    if seat["price_cents"] > 0:
        add_fee_line(seat["family_id"], seat["price_cents"])
    return success(public(seat), status=200)


@bp.route("/seats/<sid>/release", methods=["POST"])
def release_seat(sid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    seat = lookup(db.seats, sid)
    require_owner(role, user_id, seat["family_id"])
    recital = db.recitals.get(seat["recital_id"])

    if seat["status"] == "HELD":
        seat["status"] = "RELEASED"
        touch(seat)
        if recital is not None:
            recital["seats_sold"] -= 1
            touch(recital)
            _maybe_on_sale(recital)
            _recompute_family_allotment(recital, seat["family_id"])
    elif seat["status"] == "PURCHASED":
        # PURCHASED release is a StudioAdmin action with refund compensation.
        if role != "StudioAdmin":
            raise err("ERR_FORBIDDEN_ROLE", "Only an admin may release a purchased seat.")
        seat["status"] = "RELEASED"
        touch(seat)
        if recital is not None:
            recital["seats_sold"] -= 1
            touch(recital)
        # Refund the paid price to the family's account credit.
        if seat["price_cents"] > 0:
            credit_family(seat["family_id"], seat["price_cents"])
        if recital is not None:
            _maybe_on_sale(recital)
            _recompute_family_allotment(recital, seat["family_id"])
    else:
        raise err("ERR_INVALID_STATE", "Seat cannot be released.")
    return success(public(seat), status=200)
