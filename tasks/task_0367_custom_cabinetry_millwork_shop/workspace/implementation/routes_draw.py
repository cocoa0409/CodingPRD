"""Draw routes: create progress draw + issue/pay/void lifecycle."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_enum, require_int,
                     parse_pagination, paginate, sort_by_created)
from models import touch, serialize_draw, project_billed_to_date
from lookups import (get_project_in_shop, get_draw_in_project, require_project_owner)
from calculations import draw_amount, draw_settlement
from services import create_draw

bp = Blueprint("draw", __name__)


@bp.route("/shops/<shop_id>/projects/<project_id>/draws", methods=["POST"])
def create_progress_draw(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    body = get_body()
    draw_type = require_enum(body, "draw_type", {"DEPOSIT", "PROGRESS", "RETAINAGE"})
    requested_pct_bps = None
    if draw_type == "PROGRESS":
        requested_pct_bps = require_int(body, "requested_pct_bps", required=False, default=0, minimum=0)
    else:
        # requested_pct_bps ignored for DEPOSIT/RETAINAGE
        requested_pct_bps = None
    due_utc = body.get("due_utc")
    if due_utc is not None and not isinstance(due_utc, str):
        raise err("ERR_INVALID_REQUEST", "due_utc must be an ISO8601 string")

    rec = create_draw(p, draw_type, requested_pct_bps=requested_pct_bps, due_utc=due_utc)
    return success(serialize_draw(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/draws/<draw_id>", methods=["GET"])
def get_draw(shop_id, project_id, draw_id):
    user_id, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    p = get_project_in_shop(shop_id, project_id)
    d = get_draw_in_project(shop_id, project_id, draw_id)
    require_project_owner(p, user_id, role)
    return success(serialize_draw(d), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/draws", methods=["GET"])
def list_draws(shop_id, project_id):
    user_id, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    p = get_project_in_shop(shop_id, project_id)
    require_project_owner(p, user_id, role)
    limit, offset = parse_pagination()
    draw_type = request.args.get("draw_type")
    status = request.args.get("status")
    items = [d for d in store.draws.values() if d["project_id"] == project_id]
    if draw_type is not None:
        items = [d for d in items if d["draw_type"] == draw_type]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_draw(d) for d in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/draws/<draw_id>/issue", methods=["POST"])
def issue_draw(shop_id, project_id, draw_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    d = get_draw_in_project(shop_id, project_id, draw_id)
    if d["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Draw is not PENDING")
    cust = store.customers[p["customer_id"]]
    if cust["credit_hold"]:
        raise err("ERR_CUSTOMER_CREDIT_HOLD", "Customer is on credit hold")
    if d["amount_cents"] <= 0:
        raise err("ERR_EMPTY_DRAW", "Draw amount is zero")
    d["status"] = "ISSUED"
    touch(d)
    # billed_to_date is computed, but bump project for consistency.
    touch(p)
    return success(serialize_draw(d), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/draws/<draw_id>/pay", methods=["POST"])
def pay_draw(shop_id, project_id, draw_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer"})
    p = get_project_in_shop(shop_id, project_id)
    require_project_owner(p, user_id, role)
    d = get_draw_in_project(shop_id, project_id, draw_id)
    if d["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Draw is not ISSUED")
    shop = store.shops[p["shop_id"]]
    d["late_fee_cents"] = draw_settlement(d, shop)
    d["status"] = "PAID"
    touch(d)
    # paid_to_date / lifetime_paid are computed; bump project & customer.
    touch(p)
    cust = store.customers[p["customer_id"]]
    touch(cust)
    return success(serialize_draw(d), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/draws/<draw_id>/void", methods=["POST"])
def void_draw(shop_id, project_id, draw_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    d = get_draw_in_project(shop_id, project_id, draw_id)
    if d["status"] not in ("PENDING", "ISSUED"):
        raise err("ERR_INVALID_STATE", "Draw cannot be voided from %s" % d["status"])
    was_issued = d["status"] == "ISSUED"
    d["status"] = "VOIDED"
    touch(d)
    if was_issued:
        # billed_to_date is computed from ISSUED/PAID; voiding removes it. Bump project.
        touch(p)
    return success(serialize_draw(d), 200)
