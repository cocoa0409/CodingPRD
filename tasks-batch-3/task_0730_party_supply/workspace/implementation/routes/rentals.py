from __future__ import annotations
from flask import Blueprint, request

from db import db, stamp_common, bump, parse_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FK_NOT_FOUND,
    ERR_RENTAL_CATEGORY_INVALID,
    ERR_RENTAL_OVERLAP_CAPACITY,
)
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, as_int, fetch, clean
from services import order as osvc
from services import calc

bp = Blueprint("rentals", __name__)


NON_TERMINAL_RENTAL = {"RESERVED", "PICKED_UP"}


@bp.route("/rental-contracts", methods=["POST"])
@require_roles("StoreClerk")
def create_rental():
    body = get_body()
    order_id = require_field(body, "order_id")
    sku_id = require_field(body, "sku_id")
    qty = as_int(require_field(body, "qty"), "qty")
    rental_start = require_field(body, "rental_start")
    rental_end = require_field(body, "rental_end")

    # priority 5: FK existence
    if order_id not in db.orders:
        raise_error(ERR_FK_NOT_FOUND, f"order_id {order_id} not found")
    if sku_id not in db.skus:
        raise_error(ERR_FK_NOT_FOUND, f"sku_id {sku_id} not found")

    order = db.orders[order_id]
    sku = db.skus[sku_id]

    # state: rental attaches while parent Order is DRAFT
    if order["fulfillment_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "rental attach requires DRAFT order")

    if qty < 1:
        raise_error(ERR_INVALID_REQUEST, "qty must be >= 1")

    try:
        rs = parse_iso(rental_start)
        re_dt = parse_iso(rental_end)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "rental_start/rental_end must be ISO 8601")
        return
    if not (rs < re_dt):
        raise_error(ERR_INVALID_REQUEST, "rental_start must precede rental_end")

    # priority 9: category check
    if sku["category"] != "TABLEWARE":
        raise_error(ERR_RENTAL_CATEGORY_INVALID, "sku must be TABLEWARE")

    # priority 13: aggregate overlap capacity
    concurrent = qty
    for other in db.rental_contracts.values():
        if other["sku_id"] != sku_id:
            continue
        if other["status"] not in NON_TERMINAL_RENTAL:
            continue
        ors_ = parse_iso(other["rental_start"])
        ore = parse_iso(other["rental_end"])
        if rs < ore and ors_ < re_dt:
            concurrent += int(other["qty"])
    if concurrent > int(sku["on_hand_qty"]):
        raise_error(
            ERR_RENTAL_OVERLAP_CAPACITY,
            f"Overlap qty {concurrent} exceeds on_hand_qty {sku['on_hand_qty']}",
        )

    deposit = calc.rental_deposit(int(sku["unit_price_cents"]), qty)
    rc = {
        "order_id": order_id,
        "sku_id": sku_id,
        "qty": qty,
        "rental_start": rental_start,
        "rental_end": rental_end,
        "deposit_cents": deposit,
        "status": "RESERVED",
        "returned_at": None,
    }
    stamp_common(rc)
    db.rental_contracts[rc["id"]] = rc
    return created(clean(rc))


@bp.route("/rental-contracts/<id>", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def get_rental(id):
    return ok(clean(fetch(db.rental_contracts, id)))


@bp.route("/rental-contracts", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def list_rentals():
    limit, offset = parse_limit_offset()
    order_id = request.args.get("order_id")
    sku_id = request.args.get("sku_id")
    status = request.args.get("status")
    items = list(db.rental_contracts.values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if sku_id is not None:
        items = [r for r in items if r["sku_id"] == sku_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/rental-contracts/<id>/return", methods=["POST"])
@require_roles("StoreClerk")
def return_rental(id):
    rc = fetch(db.rental_contracts, id)
    if rc["status"] != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "return requires PICKED_UP")

    rental_end = parse_iso(rc["rental_end"])
    now = db.clock
    on_time = now < rental_end

    rc["returned_at"] = _iso_of(now)
    sku = db.skus.get(rc["sku_id"])
    if sku is not None:
        sku["on_hand_qty"] = int(sku["on_hand_qty"]) + int(rc["qty"])
        bump(sku)

    if on_time:
        rc["status"] = "RETURNED"
        order = db.orders.get(rc["order_id"])
        if order:
            cust = db.customers.get(order["customer_id"])
            if cust is not None:
                cust["store_credit_cents"] = int(cust.get("store_credit_cents", 0)) + int(
                    rc["deposit_cents"]
                )
                bump(cust)
    else:
        rc["status"] = "LATE_RETURN"
        # deposit forfeited — no store credit change

    bump(rc)
    return ok(clean(rc))


@bp.route("/rental-contracts/<id>/mark-damaged", methods=["POST"])
@require_roles("StoreClerk")
def mark_damaged(id):
    rc = fetch(db.rental_contracts, id)
    if rc["status"] != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "mark-damaged requires PICKED_UP")
    rc["status"] = "DAMAGED"
    bump(rc)
    return ok(clean(rc))


# --- helper --------------------------------------------------------------

def _iso_of(dt):
    from db import now_iso
    return now_iso(dt)
