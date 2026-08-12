"""SeatInventory routes (PRD 3.8) — holds, releases, purchases, price quotes."""

from flask import Blueprint, request

from db import store
from errors import (ERR_INSUFFICIENT_SEATS, ERR_SALES_NOT_OPEN, ERR_VALIDATION,
                    ApiError, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import (GROUP_MIN, compute_current_price,
                      current_demand_multiplier, purchase_total,
                      recompute_season_revenue)
from util import json_body, num_out, req_int, to_public, touch

bp = Blueprint("seat_inventories", __name__)

SECTIONS = ("STALLS", "BALCONY", "BOX", "GALLERY")


@bp.get("/opera/seat-inventories")
def list_inventories():
    require_roles("Any")
    return list_response(
        store.seat_inventories.values(),
        [("performance_id", "performance_id"), ("section", "section")],
    )


@bp.get("/opera/seat-inventories/<iid>")
def get_inventory(iid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.seat_inventories, iid,
                                          "SeatInventory")))


@bp.get("/opera/seat-inventories/<iid>/price-quote")
def price_quote(iid):
    require_roles("Any")
    inv = get_or_404(store.seat_inventories, iid, "SeatInventory")
    raw_qty = request.args.get("quantity")
    quantity = 1
    if raw_qty is not None:
        try:
            quantity = int(raw_qty)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "quantity must be an integer")
        if quantity < 1:
            raise ApiError(ERR_VALIDATION, 400, "quantity must be positive")
    mult = current_demand_multiplier(inv)
    group = quantity >= GROUP_MIN
    total = purchase_total(inv, quantity)
    return ok_object({
        "unit_price_cents": inv["current_price_cents"],
        "demand_multiplier": num_out(mult),
        "group_discount_applied": group,
        "total_price_cents": total,
    })


def _body_quantity():
    body = json_body()
    return req_int(body, "quantity", min_value=1)


def _require_on_sale(inv):
    perf = store.performances[inv["performance_id"]]
    if perf["sales_status"] != "ON_SALE":
        raise conflict(ERR_SALES_NOT_OPEN,
                       "Operation requires the performance sales status ON_SALE")
    return perf


@bp.post("/opera/seat-inventories/<iid>/hold")
def hold_seats(iid):
    require_roles("BoxOfficeManager")
    quantity = _body_quantity()
    inv = get_or_404(store.seat_inventories, iid, "SeatInventory")
    _require_on_sale(inv)
    available = inv["total_seats"] - inv["seats_held"] - inv["seats_sold"]
    if quantity > available:
        raise conflict(ERR_INSUFFICIENT_SEATS, "Not enough available seats")
    inv["seats_held"] += quantity
    touch(inv)
    return ok_object(to_public(inv))


@bp.post("/opera/seat-inventories/<iid>/release")
def release_seats(iid):
    require_roles("BoxOfficeManager")
    quantity = _body_quantity()
    inv = get_or_404(store.seat_inventories, iid, "SeatInventory")
    # Release is not gated on the sales dimension (PRD 3.8).
    if quantity > inv["seats_held"]:
        raise conflict(ERR_INSUFFICIENT_SEATS, "Not enough held seats")
    inv["seats_held"] -= quantity
    touch(inv)
    return ok_object(to_public(inv))


@bp.post("/opera/seat-inventories/<iid>/purchase")
def purchase_seats(iid):
    require_roles("BoxOfficeManager")
    quantity = _body_quantity()
    inv = get_or_404(store.seat_inventories, iid, "SeatInventory")
    perf = _require_on_sale(inv)
    available = inv["total_seats"] - inv["seats_held"] - inv["seats_sold"]
    if quantity > available:
        raise conflict(ERR_INSUFFICIENT_SEATS, "Not enough available seats")
    # Charge at the pre-purchase demand ratio, then move the seats.
    total = purchase_total(inv, quantity)
    inv["seats_sold"] += quantity
    inv["current_price_cents"] = compute_current_price(inv)
    touch(inv)
    perf["realized_revenue_cents"] += total
    touch(perf)
    prod = store.productions[perf["production_id"]]
    recompute_season_revenue(prod)
    return ok_object(to_public(inv))
