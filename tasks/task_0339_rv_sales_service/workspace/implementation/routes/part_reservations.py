"""Part reservation routes (PRD 3.7)."""

from flask import Blueprint, request

import db
import errors
from common import body, new_entity, paginate, get_or_404, invalid
from middleware import get_auth, require_role
from response import ok, created, ok_list
from services import recompute_part

bp = Blueprint("part_reservations", __name__)


@bp.post("/part-reservations")
def create_reservation():
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    data = body()
    so = get_or_404("service_orders", data.get("service_order_id"))
    part = get_or_404("part_items", data.get("part_item_id"))

    quantity = data.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        invalid("quantity must be an integer.")

    # Capacity check (priority 10) precedes the field-level >=1 check (priority 13).
    if quantity > part["qty_available"]:
        errors.err("ERR_INSUFFICIENT_PARTS", "Reservation exceeds available stock.")
    if quantity < 1:
        invalid("quantity must be >= 1.")

    rec = new_entity({
        "dealership_id": so["dealership_id"],
        "service_order_id": so["id"],
        "part_item_id": part["id"],
        "quantity": quantity,
        "unit_price_cents": part["unit_price_cents"],
        "status": "RESERVED",
    })
    db.store["part_reservations"][rec["id"]] = rec
    # Cascade: recompute the part's reserved/available figures.
    recompute_part(part)
    from common import touch
    touch(part)
    return created(rec)


@bp.get("/part-reservations")
def list_reservations():
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    items = list(db.store["part_reservations"].values())
    a = request.args
    for field in ("service_order_id", "part_item_id", "status", "dealership_id"):
        val = a.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/part-reservations/<res_id>")
def get_reservation(res_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    rec = db.store["part_reservations"].get(res_id)
    if rec is None:
        from errors import ApiError
        raise ApiError("ERR_PART_RESERVATION_NOT_FOUND", 404, "Part reservation not found.")
    return ok(rec)
