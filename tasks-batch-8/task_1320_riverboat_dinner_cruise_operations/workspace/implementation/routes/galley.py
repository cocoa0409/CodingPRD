"""Galley provision orders: create (DRAFT), list, place, receive."""
from decimal import Decimal
from flask import Blueprint, request

import clock
import db
from errors import ApiError, err_invalid_request, err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from util import require_auth, paginate, get_or_404, touch

bp = Blueprint("galley", __name__)

GALLEY = ["GalleyManager"]
GALLEY_READ = ["OperationsManager", "Captain", "GalleyManager"]

ORDER_STATUSES = ["DRAFT", "PLACED", "RECEIVED", "SETTLED", "CANCELLED"]


def _provisional_covers(cruise_id):
    total = 0
    for b in db.bookings.values():
        if (b["cruise_id"] == cruise_id
                and b["booking_status"] in ("RESERVED", "CONFIRMED")
                and b["payment_status"] in ("PENDING", "PAID")):
            total += b["party_size"]
    return total


def _load_units(cruise, covers):
    tier = db.menu_tiers[cruise["menu_tier_id"]]
    value = (Decimal(covers) * Decimal(str(tier["galley_load_per_cover"]))).quantize(
        Decimal("0.01"), rounding="ROUND_HALF_UP")
    return float(value)




@bp.post("/cruises/<cid>/provision-orders")
def create_provision_order(cid):
    require_auth(GALLEY)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    # At most one non-cancelled order per cruise
    for o in db.provision_orders.values():
        if o["cruise_id"] == cruise["id"] and o["status"] != "CANCELLED":
            raise err_invalid_state("A non-cancelled provision order already exists for this cruise")
    covers = _provisional_covers(cruise["id"])
    now_z = clock.to_z(clock.now())
    order = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "cruise_id": cruise["id"],
        "provisional_covers": covers,
        "final_covers": None,
        "provision_load_units": _load_units(cruise, covers),
        "restocking_rebate_cents": 0,
        "status": "DRAFT",
        "was_placed_at_cancel": False,
    }
    db.insert(db.provision_orders, order)
    return ok(_sz("provision_order", order), status=201)


@bp.get("/cruises/<cid>/provision-orders")
def list_provision_orders(cid):
    require_auth(GALLEY_READ)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ORDER_STATUSES:
        raise err_invalid_request("Invalid value for status")
    items = [o for o in db.provision_orders.values() if o["cruise_id"] == cruise["id"]]
    if status_filter is not None:
        items = [o for o in items if o["status"] == status_filter]
    items.sort(key=lambda o: o["created_at"])
    page, meta = paginate(items)
    return ok(_szl("provision_order", page), pagination=meta)


def _load_order(cid, oid):
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    order = db.provision_orders.get(oid)
    if order is None or order["cruise_id"] != cruise["id"]:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["provision_order"], "Provision order not found")
    return cruise, order


@bp.post("/cruises/<cid>/provision-orders/<oid>/place")
def place_provision_order(cid, oid):
    require_auth(GALLEY)
    cruise, order = _load_order(cid, oid)
    if order["status"] != "DRAFT":
        raise err_invalid_state("Provision order is not DRAFT")
    if cruise["status"] != "SCHEDULED":
        raise ApiError("ERR_CRUISE_NOT_BOOKABLE", 409, "Cruise is not SCHEDULED")
    if order["provisional_covers"] < 1:
        raise ApiError("ERR_NO_COVERS_TO_PROVISION", 422,
                       "Provision order placement requires at least one provisional cover")
    order["provision_load_units"] = _load_units(cruise, order["provisional_covers"])
    order["status"] = "PLACED"
    touch(order)
    return ok(_sz("provision_order", order))


@bp.post("/cruises/<cid>/provision-orders/<oid>/receive")
def receive_provision_order(cid, oid):
    require_auth(GALLEY)
    cruise, order = _load_order(cid, oid)
    if order["status"] != "PLACED":
        raise err_invalid_state("Provision order is not PLACED")
    order["status"] = "RECEIVED"
    touch(order)
    return ok(_sz("provision_order", order))
