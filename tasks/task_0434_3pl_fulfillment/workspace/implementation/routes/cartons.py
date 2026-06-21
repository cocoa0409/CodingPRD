"""Carton read endpoints (PRD §4)."""
from flask import Blueprint, request

from db import store
from middleware import get_auth, require_roles
from response import success
from common import get_carton, parse_pagination, paginate
from serializers import serialize_carton

bp = Blueprint("cartons", __name__)

READ_ROLES = {"PackStation", "ShipStation", "BillingClerk"}


@bp.route("/cartons", methods=["GET"])
def list_cartons():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.cartons.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize_carton(r) for r in page], pagination=meta)


@bp.route("/cartons/<carton_id>", methods=["GET"])
def get_one_carton(carton_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_carton(carton_id)
    return success(serialize_carton(rec))
