"""Orders (read-only; created as a side effect of motion rulings)."""
from flask import Blueprint, request

import db
from middleware import get_actor
from response import success
from services import domain

bp = Blueprint("orders", __name__)


@bp.get("/orders/<order_id>")
def get_order(order_id):
    get_actor()
    rec = domain.get_or_404(db.orders, order_id)
    return success(domain._clean(rec), status=200)


@bp.get("/orders")
def list_orders():
    get_actor()
    args = request.args
    items = list(db.orders.values())
    for field in ("case_id", "motion_id"):
        val = args.get(field)
        if val is not None:
            items = [o for o in items if o.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(o) for o in window], status=200, pagination=pagination)
