"""BlankReservation read endpoints (PRD §2.5, §3.4)."""
from flask import Blueprint, request

from db import store
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import parse_pagination, paginate
from services.lookups import get_order, get_reservation, reservations_of_order

bp = Blueprint("reservations", __name__)


@bp.route("/orders/<order_id>/reservations", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_order_reservations(order_id):
    get_order(order_id)
    limit, offset = parse_pagination()
    blank_sku_id = request.args.get("blank_sku_id")
    status = request.args.get("status")
    items = reservations_of_order(order_id)
    if blank_sku_id is not None:
        items = [r for r in items if r["blank_sku_id"] == blank_sku_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.route("/blank-reservations/<res_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def get_reservation_route(res_id):
    return success(view(get_reservation(res_id)), status=200)


@bp.route("/blank-reservations", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_reservations():
    limit, offset = parse_pagination()
    items = list(store.blank_reservations.values())
    for key in ("order_id", "blank_sku_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)
