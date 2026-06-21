"""Delivery endpoints (PRD §3.8, §3.9)."""
from flask import Blueprint, request

import common
import errors
import lookups
from db import store
from middleware import get_user_context, require_roles
from response import success, list_success
from serializers import serialize_delivery, serialize_earnings_record
from services import delivery_service

bp = Blueprint("deliveries", __name__)


def _dasher_owns(user_id, role, delivery):
    if role == "Dasher" and delivery["dasher_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)


@bp.route("/deliveries", methods=["GET"])
def list_deliveries():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher", "Restaurant"])
    limit, offset = common.parse_pagination()
    items = list(store.deliveries.values())
    for key in ("dasher_id", "order_id"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_delivery(d) for d in page], limit, offset, total)


@bp.route("/deliveries/<did>", methods=["GET"])
def get_delivery(did):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher", "Restaurant", "Customer"])
    d = lookups.get_delivery(did)
    return success(serialize_delivery(d))


@bp.route("/deliveries/<did>/accept", methods=["POST"])
def accept_delivery(did):
    user_id, role = get_user_context()
    require_roles(role, ["Dasher"])
    delivery = lookups.get_delivery(did)
    _dasher_owns(user_id, role, delivery)
    dasher = store.dashers[delivery["dasher_id"]]
    delivery_service.accept_delivery(delivery, dasher)
    return success(serialize_delivery(delivery))


@bp.route("/deliveries/<did>/decline", methods=["POST"])
def decline_delivery(did):
    user_id, role = get_user_context()
    require_roles(role, ["Dasher"])
    delivery = lookups.get_delivery(did)
    _dasher_owns(user_id, role, delivery)
    order = store.orders[delivery["order_id"]]
    delivery_service.decline_delivery(delivery, order)
    return success(serialize_delivery(delivery))


@bp.route("/deliveries/<did>/picked-up", methods=["POST"])
def pickup_delivery(did):
    user_id, role = get_user_context()
    require_roles(role, ["Dasher"])
    delivery = lookups.get_delivery(did)
    _dasher_owns(user_id, role, delivery)
    order = store.orders[delivery["order_id"]]
    delivery_service.pickup_delivery(delivery, order)
    return success(serialize_delivery(delivery))


@bp.route("/deliveries/<did>/delivered", methods=["POST"])
def deliver_delivery(did):
    user_id, role = get_user_context()
    require_roles(role, ["Dasher"])
    delivery = lookups.get_delivery(did)
    _dasher_owns(user_id, role, delivery)
    order = store.orders[delivery["order_id"]]
    delivery_service.deliver_delivery(delivery, order)
    return success(serialize_delivery(delivery))


@bp.route("/deliveries/<did>/earnings", methods=["GET"])
def list_delivery_earnings(did):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher"])
    lookups.get_delivery(did)
    limit, offset = common.parse_pagination()
    items = [e for e in store.earnings_records.values() if e["delivery_id"] == did]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_earnings_record(e) for e in page], limit, offset, total)
