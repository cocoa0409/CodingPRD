"""Food order lines and rental lines on a reservation (PRD §3.4)."""
from flask import Blueprint, request

from db import db, new_common, touch
from errors import err
from middleware import get_identity, require_role
from response import success, array
from services import serialize, pricing, ledger
from services.util import (
    get_body, parse_pagination, paginate, lookup, as_str, as_int,
)

bp = Blueprint("lines", __name__)


def _owner_guard_res(role, user_id, res):
    if role == "Customer" and res["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this reservation")


def _reprice_held(res):
    """If the reservation is HELD, refresh held_deposit from the new quote.

    food/rental subtotals are already recomputed into res before calling this;
    reconcile the customer's deposit balance by the deposit delta (PRD §3.4).
    """
    if res["status"] == "HELD":
        rate_card = db.rate_cards.get(res["rate_card_id"])
        old_deposit = res["held_deposit_cents"]
        new_deposit = pricing.deposit_amount(res["quoted_total_cents"], rate_card)
        res["held_deposit_cents"] = new_deposit
        customer = db.customers.get(res["customer_id"])
        if customer:
            ledger.deposit_reconcile_delta(customer, new_deposit - old_deposit)


# ----------------------------------------------------------------- food lines
@bp.post("/food-lines")
def create_food_line():
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    body = get_body()
    reservation_id = as_str(body, "reservation_id")
    food_item_id = as_str(body, "food_item_id")
    quantity = as_int(body, "quantity", minimum=1)

    res = lookup(db.reservations, reservation_id, "reservation")
    _owner_guard_res(role, user_id, res)
    item = lookup(db.food_items, food_item_id, "food item")

    if res["status"] not in ("DRAFT", "HELD"):
        raise err("ERR_INVALID_STATE", "Food lines addable only while DRAFT or HELD")

    line = new_common(full=False)
    line.update({
        "reservation_id": reservation_id,
        "food_item_id": food_item_id,
        "quantity": quantity,
        "unit_cents_snapshot": item["unit_cents"],
        "taxable_snapshot": item["taxable"],
        "line_total_cents": pricing.food_line_total(item["unit_cents"], quantity, item["taxable"]),
    })
    db.food_lines[line["id"]] = line

    # Recompute reservation food subtotal + quoted total, refresh deposit if HELD.
    res["food_subtotal_cents"] = pricing.food_subtotal(reservation_id)
    res["quoted_total_cents"] = (
        res["lane_subtotal_cents"] + res["package_subtotal_cents"]
        + res["food_subtotal_cents"] + res["rental_subtotal_cents"]
    )
    _reprice_held(res)
    touch(res)
    return success(serialize.food_line(line), status=201)


@bp.get("/food-lines/<id>")
def get_food_line(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    line = lookup(db.food_lines, id, "food line")
    if role == "Customer":
        res = db.reservations.get(line["reservation_id"])
        if res and res["customer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this line")
    return success(serialize.food_line(line))


@bp.get("/food-lines")
def list_food_lines():
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    limit, offset = parse_pagination()
    items = list(db.food_lines.values())
    if role == "Customer":
        owned = {r["id"] for r in db.reservations.values() if r["customer_id"] == user_id}
        items = [l for l in items if l["reservation_id"] in owned]
    for field in ("reservation_id", "food_item_id"):
        val = request.args.get(field)
        if val:
            items = [l for l in items if l.get(field) == val]
    page, meta = paginate(items, limit, offset)
    return array([serialize.food_line(e) for e in page], pagination=meta)


@bp.delete("/food-lines/<id>")
def delete_food_line(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    line = lookup(db.food_lines, id, "food line")
    res = lookup(db.reservations, line["reservation_id"], "reservation")
    _owner_guard_res(role, user_id, res)
    if res["status"] not in ("DRAFT", "HELD"):
        raise err("ERR_INVALID_STATE", "Food lines removable only while DRAFT or HELD")

    del db.food_lines[id]
    res["food_subtotal_cents"] = pricing.food_subtotal(res["id"])
    res["quoted_total_cents"] = (
        res["lane_subtotal_cents"] + res["package_subtotal_cents"]
        + res["food_subtotal_cents"] + res["rental_subtotal_cents"]
    )
    _reprice_held(res)
    touch(res)
    return success(serialize.food_line(line))


# --------------------------------------------------------------- rental lines
@bp.post("/rental-lines")
def create_rental_line():
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    body = get_body()
    reservation_id = as_str(body, "reservation_id")
    rental_item_id = as_str(body, "rental_item_id")
    quantity = as_int(body, "quantity", minimum=1)

    res = lookup(db.reservations, reservation_id, "reservation")
    _owner_guard_res(role, user_id, res)
    item = lookup(db.rental_items, rental_item_id, "rental item")

    if res["status"] not in ("DRAFT", "HELD", "CHECKED_IN"):
        raise err("ERR_INVALID_STATE", "Rentals takeable only while DRAFT, HELD, or CHECKED_IN")

    # Suspended customer may not take a rental (PRD §3.4).
    customer = db.customers.get(res["customer_id"])
    if customer and customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_SUSPENDED", "Customer is suspended")

    # Availability (PRD §3.4 / P53).
    if quantity > item["available_count"]:
        raise err("ERR_RENTAL_UNAVAILABLE", "Requested quantity exceeds availability")

    line = new_common()
    line.update({
        "reservation_id": reservation_id,
        "rental_item_id": rental_item_id,
        "quantity": quantity,
        "unit_price_snapshot": item["unit_price_cents"],
        "line_total_cents": quantity * item["unit_price_cents"],
        "status": "OPEN",
    })
    db.rental_lines[line["id"]] = line

    # Raise out_on_rent_count, lower available_count.
    ledger.recompute_rental_item_counts(item)
    touch(item)

    res["rental_subtotal_cents"] = pricing.rental_subtotal(reservation_id)
    res["quoted_total_cents"] = (
        res["lane_subtotal_cents"] + res["package_subtotal_cents"]
        + res["food_subtotal_cents"] + res["rental_subtotal_cents"]
    )
    _reprice_held(res)
    touch(res)
    return success(serialize.rental_line(line), status=201)


@bp.get("/rental-lines/<id>")
def get_rental_line(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    line = lookup(db.rental_lines, id, "rental line")
    if role == "Customer":
        res = db.reservations.get(line["reservation_id"])
        if res and res["customer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this line")
    return success(serialize.rental_line(line))


@bp.get("/rental-lines")
def list_rental_lines():
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    limit, offset = parse_pagination()
    items = list(db.rental_lines.values())
    if role == "Customer":
        owned = {r["id"] for r in db.reservations.values() if r["customer_id"] == user_id}
        items = [l for l in items if l["reservation_id"] in owned]
    for field in ("reservation_id", "rental_item_id", "status"):
        val = request.args.get(field)
        if val:
            items = [l for l in items if l.get(field) == val]
    page, meta = paginate(items, limit, offset)
    return array([serialize.rental_line(e) for e in page], pagination=meta)


@bp.post("/rental-lines/<id>/return")
def return_rental_line(id):
    user_id, role = get_identity()
    require_role(role, {"Customer", "FrontDesk"})
    line = lookup(db.rental_lines, id, "rental line")
    res = db.reservations.get(line["reservation_id"])
    if role == "Customer":
        if res and res["customer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this line")
    if line["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Rental line is not OPEN")

    line["status"] = "RETURNED"
    touch(line)

    item = db.rental_items.get(line["rental_item_id"])
    if item:
        ledger.recompute_rental_item_counts(item)
        touch(item)

    # Returned lines no longer count toward rental_subtotal.
    if res:
        res["rental_subtotal_cents"] = pricing.rental_subtotal(res["id"])
        res["quoted_total_cents"] = (
            res["lane_subtotal_cents"] + res["package_subtotal_cents"]
            + res["food_subtotal_cents"] + res["rental_subtotal_cents"]
        )
        # Note: PRD §3.4 return only bumps the rental line's version; the
        # subtotal is kept consistent but the reservation version is NOT bumped
        # here per the scaffold side-effect list (return increments RentalLine.version).
    return success(serialize.rental_line(line))
