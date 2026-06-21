"""ChangeOrder routes and the revision loop."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_str, require_int,
                     parse_pagination, paginate, sort_by_created)
from models import _base_record, touch, serialize_change_order
from lookups import (get_project_in_shop, get_change_order_in_project,
                     require_project_owner)
from calculations import change_order_delta
from services import create_progress_adjustment_draw, recompute_deposit_required

bp = Blueprint("changeorder", __name__)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders", methods=["POST"])
def create_change_order(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    body = get_body()
    description = require_str(body, "description")
    spec_price_delta_cents = require_int(body, "spec_price_delta_cents")

    rec = _base_record()
    rec.update({
        "project_id": project_id,
        "description": description,
        "spec_price_delta_cents": spec_price_delta_cents,
        "delta_cents": None,
        "revision_round": 1,
        "status": "DRAFT",
    })
    store.change_orders[rec["id"]] = rec
    return success(serialize_change_order(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders/<co_id>", methods=["GET"])
def get_change_order(shop_id, project_id, co_id):
    user_id, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    p = get_project_in_shop(shop_id, project_id)
    c = get_change_order_in_project(shop_id, project_id, co_id)
    require_project_owner(p, user_id, role)
    return success(serialize_change_order(c), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders", methods=["GET"])
def list_change_orders(shop_id, project_id):
    user_id, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    p = get_project_in_shop(shop_id, project_id)
    require_project_owner(p, user_id, role)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [c for c in store.change_orders.values() if c["project_id"] == project_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_change_order(c) for c in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders/<co_id>/submit", methods=["POST"])
def submit_change_order(shop_id, project_id, co_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    c = get_change_order_in_project(shop_id, project_id, co_id)
    body = get_body()
    expected_version = require_int(body, "expected_project_version")
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Change order is not DRAFT")
    if p["status"] != "IN_PRODUCTION":
        raise err("ERR_INVALID_STATE", "Project is not IN_PRODUCTION")
    if expected_version != p["version"]:
        raise err("ERR_STALE_VERSION", "expected_project_version does not match")

    c["delta_cents"] = change_order_delta(p, c["spec_price_delta_cents"])
    c["status"] = "SUBMITTED"
    touch(c)
    p["status"] = "CHANGE_PENDING"
    touch(p)  # increments project version by 1
    return success(serialize_change_order(c), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders/<co_id>/request-revision", methods=["POST"])
def request_revision(shop_id, project_id, co_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer"})
    p = get_project_in_shop(shop_id, project_id)
    require_project_owner(p, user_id, role)
    c = get_change_order_in_project(shop_id, project_id, co_id)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Change order is not SUBMITTED")
    c["status"] = "REVISING"
    touch(c)
    return success(serialize_change_order(c), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders/<co_id>/resubmit", methods=["POST"])
def resubmit_change_order(shop_id, project_id, co_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    c = get_change_order_in_project(shop_id, project_id, co_id)
    if c["status"] != "REVISING":
        raise err("ERR_INVALID_STATE", "Change order is not REVISING")
    c["revision_round"] += 1
    c["delta_cents"] = change_order_delta(p, c["spec_price_delta_cents"])
    c["status"] = "SUBMITTED"
    touch(c)
    return success(serialize_change_order(c), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders/<co_id>/approve", methods=["POST"])
def approve_change_order(shop_id, project_id, co_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer"})
    p = get_project_in_shop(shop_id, project_id)
    require_project_owner(p, user_id, role)
    c = get_change_order_in_project(shop_id, project_id, co_id)
    body = get_body()
    expected_version = require_int(body, "expected_project_version")
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Change order is not SUBMITTED")
    if expected_version != p["version"]:
        raise err("ERR_STALE_VERSION", "expected_project_version does not match")

    # Freeze delta; fold into contract; recompute deposit; create PROGRESS draw for max(0,delta).
    c["status"] = "APPROVED"
    touch(c)
    delta = c["delta_cents"] or 0
    p["contract_total_cents"] += delta
    recompute_deposit_required(p)
    p["status"] = "IN_PRODUCTION"
    touch(p)  # increments project version by 1
    create_progress_adjustment_draw(p, delta)
    return success(serialize_change_order(c), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders/<co_id>/reject", methods=["POST"])
def reject_change_order(shop_id, project_id, co_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer"})
    p = get_project_in_shop(shop_id, project_id)
    require_project_owner(p, user_id, role)
    c = get_change_order_in_project(shop_id, project_id, co_id)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Change order is not SUBMITTED")
    c["status"] = "REJECTED"
    touch(c)
    p["status"] = "IN_PRODUCTION"
    touch(p)  # increments project version by 1
    return success(serialize_change_order(c), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/change-orders/<co_id>/cancel", methods=["POST"])
def cancel_change_order(shop_id, project_id, co_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    c = get_change_order_in_project(shop_id, project_id, co_id)
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Change order is not DRAFT")
    c["status"] = "CANCELLED"
    touch(c)
    return success(serialize_change_order(c), 200)
