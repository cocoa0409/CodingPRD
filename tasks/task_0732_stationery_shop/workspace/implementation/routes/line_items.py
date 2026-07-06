"""Read-only line item endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import models
import response as resp
import util

bp = Blueprint("line_items", __name__)


@bp.route("/orders/<oid>/line-items", methods=["GET"])
def list_order_line_items(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])
    limit, offset = util.get_pagination()
    items = [li for li in db.line_items.values() if li["order_id"] == oid]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)


@bp.route("/line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    li = models.get_line_item(lid)
    if role == "Customer":
        o = db.orders.get(li["order_id"])
        if not o or o["customer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "not your line item")
    return resp.ok(li)


@bp.route("/line-items", methods=["GET"])
def list_line_items():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    limit, offset = util.get_pagination()

    def match(li):
        oid = request.args.get("order_id")
        pid = request.args.get("paper_stock_id")
        fid = request.args.get("finish_option_id")
        if oid and li["order_id"] != oid:
            return False
        if pid and li["paper_stock_id"] != pid:
            return False
        if fid and li["finish_option_id"] != fid:
            return False
        return True

    items = [li for li in db.line_items.values() if match(li)]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
