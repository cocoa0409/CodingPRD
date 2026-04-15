"""Customer routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_CUSTOMER_NOT_FOUND, ERR_DUPLICATE_PHONE, ERR_VERSION_CONFLICT
from middleware import require_roles
from response import success_response
from services.calculations import create_wallet_transaction

bp = Blueprint("customers", __name__)


def _get_customer_or_404(cid):
    c = db.customers.get(cid)
    if not c:
        raise_error(ERR_CUSTOMER_NOT_FOUND, "The referenced customer does not exist.")
    return c


@bp.route("/platform/customers", methods=["POST"])
def create_customer():
    require_roles("platform_admin", "customer")
    body = req.get_json(force=True, silent=True) or {}
    phone = body.get("phone")
    # unique phone check
    for c in db.customers.values():
        if c["phone"] == phone:
            raise_error(ERR_DUPLICATE_PHONE, "Phone number is already registered.")
    now = db.now_iso()
    c = {
        "id": db.new_id(),
        "name": body.get("name"),
        "phone": phone,
        "default_address": body.get("default_address"),
        "default_latitude": body.get("default_latitude"),
        "default_longitude": body.get("default_longitude"),
        "status": "ACTIVE",
        "wallet_balance_cents": 0,
        "loyalty_points": 0,
        "total_orders": 0,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.customers[c["id"]] = c
    return success_response(c, 201)


@bp.route("/platform/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    require_roles("customer", "platform_admin", "customer_service")
    c = _get_customer_or_404(customer_id)
    return success_response(c)


@bp.route("/platform/customers/<customer_id>", methods=["PATCH"])
def update_customer(customer_id):
    require_roles("customer")
    c = _get_customer_or_404(customer_id)
    body = req.get_json(force=True, silent=True) or {}
    if "version" in body and body["version"] is not None:
        if body["version"] != c["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch.")
    # check phone uniqueness if updating
    if "phone" in body and body["phone"] != c["phone"]:
        for existing in db.customers.values():
            if existing["phone"] == body["phone"] and existing["id"] != customer_id:
                raise_error(ERR_DUPLICATE_PHONE, "Phone number is already registered.")
    for key in ("name", "phone", "default_address", "default_latitude", "default_longitude"):
        if key in body:
            c[key] = body[key]
    c["updated_at"] = db.now_iso()
    c["version"] += 1
    return success_response(c)


@bp.route("/platform/customers/<customer_id>/wallet/top-up", methods=["POST"])
def wallet_topup(customer_id):
    require_roles("customer")
    c = _get_customer_or_404(customer_id)
    body = req.get_json(force=True, silent=True) or {}
    amount = body.get("amount_cents", 0)
    create_wallet_transaction(customer_id, "TOP_UP", amount)
    return success_response(c)
