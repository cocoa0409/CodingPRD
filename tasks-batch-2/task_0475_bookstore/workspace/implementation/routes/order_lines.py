"""Cross-store OrderLine reads."""
from flask import Blueprint, request

from common import parse_pagination, paginate
from db import db
from errors import err, ERR_NOT_FOUND
from middleware import authorize, check_owner
from response import success_object, success_list
from serialize import order_line_out

bp = Blueprint("order_lines", __name__)

ORDER_ROLES = {"Member", "Bookseller", "StoreAdmin"}


@bp.route("/order-lines/<lid>", methods=["GET"])
def get_order_line(lid):
    user_id, role = authorize(ORDER_ROLES)
    line = db.order_lines.get(lid)
    if line is None:
        raise err(ERR_NOT_FOUND, "Order line not found")
    # ownership via the owning order's member
    order = db.sales_orders.get(line["order_id"])
    if order is not None:
        check_owner(user_id, role, order["member_id"])
    return success_object(order_line_out(line), status=200)


@bp.route("/order-lines", methods=["GET"])
def list_order_lines():
    user_id, role = authorize(ORDER_ROLES)
    title_id = request.args.get("title_id")
    order_id = request.args.get("order_id")
    items = list(db.order_lines.values())
    if role == "Member":
        own_orders = {o["id"] for o in db.sales_orders.values() if o["member_id"] == user_id}
        items = [l for l in items if l["order_id"] in own_orders]
    if title_id is not None:
        items = [l for l in items if l["title_id"] == title_id]
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([order_line_out(l) for l in page], limit, offset, total)
