"""Capacity reservation read routes (PRD §4)."""

from flask import Blueprint, request

import db
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services.common import lookup, list_collection

bp = Blueprint("capacity", __name__)


@bp.get("/capacity-reservations")
@require_roles("ShopStaff", "ProductionOperator")
def list_capacity_reservations():
    shop_id = request.args.get("shop_id")
    order_line_id = request.args.get("order_line_id")
    production_date = request.args.get("production_date")

    def pred(r):
        if shop_id is not None and r["shop_id"] != shop_id:
            return False
        if order_line_id is not None and r["order_line_id"] != order_line_id:
            return False
        if production_date is not None and r["production_date"] != production_date:
            return False
        return True

    items, limit, offset, total = list_collection(db.capacity_reservations, pred)
    return array_response([serialize.capacity_reservation(r) for r in items],
                          limit, offset, total)


@bp.get("/capacity-reservations/<capacity_reservation_id>")
@require_roles("ShopStaff", "ProductionOperator")
def read_capacity_reservation(capacity_reservation_id):
    rec = lookup(db.capacity_reservations, capacity_reservation_id)
    return object_response(serialize.capacity_reservation(rec), 200)
