"""ServiceItem + Customer routes."""
from flask import Blueprint, request

from db import store
from errors import ERR_NOT_FOUND, raise_error
from response import success_response
from middleware import require_roles
from services import catalog as svc
from services.utils import parse_pagination, paginate


bp = Blueprint("catalog", __name__)


# ---------- Service Items ----------
@bp.route("/dsd/service-items", methods=["POST"])
def create_item():
    require_roles({"PlatformOperator"})
    body = request.get_json(silent=True) or {}
    item = svc.create_service_item(body)
    return success_response(item, http_status=201)


@bp.route("/dsd/service-items", methods=["GET"])
def list_items():
    require_roles({"PlatformOperator", "Customer"})
    limit, offset = parse_pagination()
    items = list(store.service_items.values())
    area = request.args.get("area_code")
    active_q = request.args.get("active")
    if area:
        items = [x for x in items if area in x.get("service_areas", [])]
    if active_q is not None:
        bv = active_q.lower() in ("true", "1", "yes")
        items = [x for x in items if x["active"] == bv]
    window, page = paginate(items, limit, offset)
    return success_response(window, pagination=page)


@bp.route("/dsd/service-items/<iid>", methods=["PATCH"])
def update_item(iid):
    require_roles({"PlatformOperator"})
    if iid not in store.service_items:
        raise_error(ERR_NOT_FOUND, "Service item not found")
    body = request.get_json(silent=True) or {}
    item = svc.update_service_item(iid, body)
    return success_response(item)


# ---------- Customers ----------
@bp.route("/dsd/customers", methods=["POST"])
def create_customer():
    require_roles({"PlatformOperator"})
    body = request.get_json(silent=True) or {}
    c = svc.create_customer(body)
    return success_response(c, http_status=201)


@bp.route("/dsd/customers/<cid>", methods=["GET"])
def get_customer(cid):
    role, user_id = require_roles({"PlatformOperator", "Customer"})
    if cid not in store.customers:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    # Customer ownership: a Customer caller can only read their own profile
    if role == "Customer" and user_id != cid:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    return success_response(store.customers[cid])
