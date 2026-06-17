"""Notification endpoints (PRD §3.9)."""
from flask import Blueprint

import validate
from db import db
from middleware import get_auth, require_role
from response import ok_array
from services import domain
from routes.orders import find_order_or_404, assert_customer_owns_order

bp = Blueprint("notifications", __name__)


@bp.route("/framing-orders/<order_id>/notifications", methods=["GET"])
def list_order_notifications(order_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk", "FrameDesigner", "FrameProductionTech", "Customer"))
    o = find_order_or_404(order_id)
    assert_customer_owns_order(auth, o)
    limit, offset = validate.parse_pagination()
    items = [n for n in db.notifications.values() if n["order_id"] == order_id]
    items.sort(key=lambda n: (n["created_at"], n["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_notification(n) for n in page], limit, offset, total)
