"""Fundraisers, orders, and booth reservations (PRD §3.7, §3.8)."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_INSUFFICIENT_INVENTORY,
    ERR_BOOTH_CONFLICT,
)
from middleware import authenticate, require_roles, BOTH_ROLES, REGISTRAR_ONLY, LEADER_ONLY
from response import object_response, array_response
from serializers import (
    serialize_fundraiser,
    serialize_fundraiser_order,
    serialize_booth_reservation,
)
from util import new_id, iso_now, parse_iso_datetime
from routes import helpers as h
from services import recompute, calculations
from services.ledger import post_ledger_entry

bp = Blueprint("fundraisers", __name__)

PRODUCTS = {"COOKIES", "POPCORN"}


@bp.post("/councils/<council_id>/fundraisers")
def create_fundraiser(council_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    council = h.get_or_404(db.councils, council_id)
    body = h.get_json_body()

    product = h.require_enum(body, "product", PRODUCTS)
    unit_price_cents = h.require_int(body, "unit_price_cents")
    unit_cost_cents = h.require_int(body, "unit_cost_cents")
    total_inventory_units = h.require_int(body, "total_inventory_units")

    # PRD §3.7: unit_price > 0, unit_cost >= 0, total_inventory >= 0.
    if unit_price_cents <= 0:
        raise err(ERR_INVALID_REQUEST, "unit_price_cents must be > 0")
    if unit_cost_cents < 0:
        raise err(ERR_INVALID_REQUEST, "unit_cost_cents must be >= 0")
    if total_inventory_units < 0:
        raise err(ERR_INVALID_REQUEST, "total_inventory_units must be >= 0")

    now = iso_now(datetime.now(timezone.utc))
    fundraiser = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "council_id": council["id"],
        "product": product,
        "unit_price_cents": unit_price_cents,
        "unit_cost_cents": unit_cost_cents,
        "total_inventory_units": total_inventory_units,
        "allocated_units": 0,
        "available_units": total_inventory_units,
        "status": "DRAFT",
        "_seq": db.next_seq(),
    }
    db.fundraisers[fundraiser["id"]] = fundraiser
    return object_response(serialize_fundraiser(fundraiser), status=201)


@bp.get("/fundraisers/<fundraiser_id>")
def get_fundraiser(fundraiser_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    fundraiser = h.get_or_404(db.fundraisers, fundraiser_id)
    recompute.refresh_fundraiser_inventory(fundraiser)
    return object_response(serialize_fundraiser(fundraiser))


@bp.get("/fundraisers")
def list_fundraisers():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    council_id = request.args.get("council_id")
    status = request.args.get("status")
    limit, offset = h.parse_pagination()
    rows = [
        f for f in db.fundraisers.values()
        if (council_id is None or f["council_id"] == council_id)
        and (status is None or f["status"] == status)
    ]
    rows = h.sort_by_creation(rows)
    for f in rows:
        recompute.refresh_fundraiser_inventory(f)
    page, total = h.paginate(rows, limit, offset)
    return array_response([serialize_fundraiser(f) for f in page], limit, offset, total)


@bp.post("/fundraisers/<fundraiser_id>/go-live")
def go_live(fundraiser_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    fundraiser = h.get_or_404(db.fundraisers, fundraiser_id)
    # DRAFT and total_inventory_units >= 1 (PRD §3.7).
    if fundraiser["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "go-live only from DRAFT")
    if fundraiser["total_inventory_units"] < 1:
        raise err(ERR_INVALID_STATE, "go-live requires at least one unit of inventory")
    fundraiser["status"] = "LIVE"
    h.touch_and_bump(fundraiser)
    recompute.refresh_fundraiser_inventory(fundraiser)
    return object_response(serialize_fundraiser(fundraiser))


@bp.post("/fundraisers/<fundraiser_id>/close")
def close_fundraiser(fundraiser_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    fundraiser = h.get_or_404(db.fundraisers, fundraiser_id)
    if fundraiser["status"] != "LIVE":
        raise err(ERR_INVALID_STATE, "close only from LIVE")
    fundraiser["status"] = "CLOSED"

    # Auto-cancel every PLACED order; reverse its commission (PRD §3.7).
    touched_troops = set()
    for order in db.fundraiser_orders.values():
        if order["fundraiser_id"] == fundraiser["id"] and order["status"] == "PLACED":
            order["status"] = "CANCELLED"
            h.touch_and_bump(order)
            _reverse_commission(order, fundraiser)
            touched_troops.add(order["troop_id"])

    recompute.refresh_fundraiser_inventory(fundraiser)
    h.touch_and_bump(fundraiser)

    # Recompute affected troops (dues_account changed) with version bumps.
    for tid in touched_troops:
        troop = db.troops.get(tid)
        if troop is not None:
            recompute.recompute_troop_counts(troop, bump=True)
    return object_response(serialize_fundraiser(fundraiser))


def _reverse_commission(order, fundraiser):
    """Post a REVERSAL ledger entry unwinding the order's commission."""
    post_ledger_entry(
        fundraiser["council_id"],
        "TROOP_DUES",
        -order["troop_commission_cents"],
        "REVERSAL",
        order["id"],
        troop_id=order["troop_id"],
    )


# ---------------------------------------------------------------------------
# Fundraiser orders
# ---------------------------------------------------------------------------
orders_bp = Blueprint("fundraiser_orders", __name__)


@orders_bp.post("/fundraiser-orders")
def place_order():
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    body = h.get_json_body()

    fundraiser_id = h.require_string(body, "fundraiser_id")
    troop_id = h.require_string(body, "troop_id")
    seller_member_id = h.require_string(body, "seller_member_id")
    units = h.require_int(body, "units")
    expected_version = h.require_field(body, "expected_fundraiser_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err(ERR_INVALID_REQUEST, "expected_fundraiser_version must be an integer")

    # Body FK integrity (PRD §2.7) -> ERR_INVALID_REFERENCE.
    fundraiser = db.fundraisers.get(fundraiser_id)
    troop = db.troops.get(troop_id)
    seller = db.members.get(seller_member_id)
    if fundraiser is None or troop is None or seller is None:
        raise err(ERR_INVALID_REFERENCE, "fundraiser_id, troop_id, or seller_member_id invalid")
    # seller_member_id's troop must match the order's troop_id (PRD §2.7).
    if seller["troop_id"] != troop_id:
        raise err(ERR_INVALID_REFERENCE, "seller_member_id does not belong to troop_id")

    # State: only a LIVE fundraiser accepts orders (PRD §3.7) -> ERR_INVALID_STATE.
    if fundraiser["status"] != "LIVE":
        raise err(ERR_INVALID_STATE, "fundraiser is not LIVE")

    # OCC: expected_fundraiser_version must match (PRD §2.6) -> ERR_STALE_VERSION.
    if expected_version != fundraiser["version"]:
        raise err(ERR_STALE_VERSION, "expected_fundraiser_version does not match")

    # units >= 1 (PRD §3.7) -> ERR_INVALID_REQUEST.
    if units < 1:
        raise err(ERR_INVALID_REQUEST, "units must be >= 1")

    # Inventory: units <= available_units (PRD §3.7) -> ERR_INSUFFICIENT_INVENTORY.
    recompute.refresh_fundraiser_inventory(fundraiser)
    if units > fundraiser["available_units"]:
        raise err(ERR_INSUFFICIENT_INVENTORY, "units exceed available inventory")

    gross = units * fundraiser["unit_price_cents"]
    commission = calculations.tiered_commission(units, fundraiser["unit_price_cents"])

    now = iso_now(datetime.now(timezone.utc))
    order = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fundraiser_id": fundraiser["id"],
        "troop_id": troop_id,
        "seller_member_id": seller_member_id,
        "units": units,
        "gross_cents": gross,
        "troop_commission_cents": commission,
        "status": "PLACED",
        "_seq": db.next_seq(),
    }
    db.fundraiser_orders[order["id"]] = order

    # Credit commission into TROOP_DUES (source_kind=FUNDRAISER_ORDER).
    post_ledger_entry(
        fundraiser["council_id"], "TROOP_DUES", commission, "FUNDRAISER_ORDER",
        order["id"], troop_id=troop_id,
    )

    # Fundraiser inventory recompute + version bump (PRD §2.6).
    recompute.refresh_fundraiser_inventory(fundraiser)
    h.touch_and_bump(fundraiser)
    # Troop dues_account changed -> recompute + version bump (PRD §2.5).
    recompute.recompute_troop_counts(troop, bump=True)
    return object_response(serialize_fundraiser_order(order), status=201)


@orders_bp.get("/fundraiser-orders/<order_id>")
def get_order(order_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    order = h.get_or_404(db.fundraiser_orders, order_id)
    return object_response(serialize_fundraiser_order(order))


@orders_bp.get("/fundraiser-orders")
def list_orders():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    fundraiser_id = request.args.get("fundraiser_id")
    troop_id = request.args.get("troop_id")
    seller_member_id = request.args.get("seller_member_id")
    limit, offset = h.parse_pagination()
    rows = [
        o for o in db.fundraiser_orders.values()
        if (fundraiser_id is None or o["fundraiser_id"] == fundraiser_id)
        and (troop_id is None or o["troop_id"] == troop_id)
        and (seller_member_id is None or o["seller_member_id"] == seller_member_id)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response(
        [serialize_fundraiser_order(o) for o in page], limit, offset, total
    )


@orders_bp.post("/fundraiser-orders/<order_id>/fill")
def fill_order(order_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    order = h.get_or_404(db.fundraiser_orders, order_id)
    fundraiser = db.fundraisers[order["fundraiser_id"]]
    # Fill only while order PLACED and fundraiser LIVE (PRD §3.7).
    if order["status"] != "PLACED" or fundraiser["status"] != "LIVE":
        raise err(ERR_INVALID_STATE, "fill requires PLACED order and LIVE fundraiser")

    order["status"] = "FILLED"
    h.touch_and_bump(order)

    # Post cash + liability ledger entries (source_kind=FUNDRAISER_ORDER).
    post_ledger_entry(
        fundraiser["council_id"], "COUNCIL_CASH", order["gross_cents"],
        "FUNDRAISER_ORDER", order["id"], troop_id=None,
    )
    post_ledger_entry(
        fundraiser["council_id"], "PRODUCT_LIABILITY",
        order["units"] * fundraiser["unit_cost_cents"],
        "FUNDRAISER_ORDER", order["id"], troop_id=None,
    )
    # Inventory unchanged on fill (FILLED still counts toward allocated).
    recompute.refresh_fundraiser_inventory(fundraiser)
    return object_response(serialize_fundraiser_order(order))


@orders_bp.post("/fundraiser-orders/<order_id>/cancel")
def cancel_order(order_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    order = h.get_or_404(db.fundraiser_orders, order_id)
    fundraiser = db.fundraisers[order["fundraiser_id"]]
    # Cancel defined from PLACED (PRD §3.7).
    if order["status"] != "PLACED":
        raise err(ERR_INVALID_STATE, "cancel only from PLACED")

    order["status"] = "CANCELLED"
    h.touch_and_bump(order)
    # Reverse commission out of TROOP_DUES.
    _reverse_commission(order, fundraiser)

    # Inventory recompute + version bump (PRD §2.6).
    recompute.refresh_fundraiser_inventory(fundraiser)
    h.touch_and_bump(fundraiser)
    # Troop dues_account changed -> recompute + version bump (PRD §2.5).
    troop = db.troops.get(order["troop_id"])
    if troop is not None:
        recompute.recompute_troop_counts(troop, bump=True)
    return object_response(serialize_fundraiser_order(order))


# ---------------------------------------------------------------------------
# Booth reservations
# ---------------------------------------------------------------------------
booth_bp = Blueprint("booth_reservations", __name__)


@bp.post("/fundraisers/<fundraiser_id>/booth-reservations")
def reserve_booth(fundraiser_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    fundraiser = h.get_or_404(db.fundraisers, fundraiser_id)
    body = h.get_json_body()

    troop_id = h.require_string(body, "troop_id")
    location_code = h.require_string(body, "location_code")
    starts_raw = h.require_string(body, "starts_at")
    ends_raw = h.require_string(body, "ends_at")

    # Body FK: troop_id must exist (PRD §2.7) -> ERR_INVALID_REFERENCE.
    if troop_id not in db.troops:
        raise err(ERR_INVALID_REFERENCE, "troop_id does not exist")

    starts_at = parse_iso_datetime(starts_raw)
    ends_at = parse_iso_datetime(ends_raw)
    if not (ends_at > starts_at):
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")

    # Booth overlap, half-open [starts_at, ends_at), scoped per location_code
    # AND per fundraiser (PRD §3.8). Touching endpoints are allowed.
    for b in db.booth_reservations.values():
        if (
            b["fundraiser_id"] == fundraiser["id"]
            and b["location_code"] == location_code
            and b["status"] == "BOOKED"
        ):
            if starts_at < b["_ends_dt"] and b["_starts_dt"] < ends_at:
                raise err(ERR_BOOTH_CONFLICT, "booth slot overlaps an existing booking")

    now = iso_now(datetime.now(timezone.utc))
    booth = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fundraiser_id": fundraiser["id"],
        "troop_id": troop_id,
        "location_code": location_code,
        "starts_at": iso_now(starts_at),
        "ends_at": iso_now(ends_at),
        "_starts_dt": starts_at,
        "_ends_dt": ends_at,
        "status": "BOOKED",
        "_seq": db.next_seq(),
    }
    db.booth_reservations[booth["id"]] = booth
    return object_response(serialize_booth_reservation(booth), status=201)


@booth_bp.get("/booth-reservations/<booth_id>")
def get_booth(booth_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    booth = h.get_or_404(db.booth_reservations, booth_id)
    return object_response(serialize_booth_reservation(booth))


@booth_bp.get("/booth-reservations")
def list_booths():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    fundraiser_id = request.args.get("fundraiser_id")
    troop_id = request.args.get("troop_id")
    location_code = request.args.get("location_code")
    limit, offset = h.parse_pagination()
    rows = [
        b for b in db.booth_reservations.values()
        if (fundraiser_id is None or b["fundraiser_id"] == fundraiser_id)
        and (troop_id is None or b["troop_id"] == troop_id)
        and (location_code is None or b["location_code"] == location_code)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response(
        [serialize_booth_reservation(b) for b in page], limit, offset, total
    )


@booth_bp.post("/booth-reservations/<booth_id>/release")
def release_booth(booth_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    booth = h.get_or_404(db.booth_reservations, booth_id)
    if booth["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "release only from BOOKED")
    booth["status"] = "RELEASED"
    h.touch_and_bump(booth)
    return object_response(serialize_booth_reservation(booth))
