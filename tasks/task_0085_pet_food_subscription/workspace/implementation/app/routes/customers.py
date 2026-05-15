"""Customer endpoints."""
from __future__ import annotations

import copy

from flask import Blueprint, request

from app.auth import assert_customer_owns, require_role
from app.calculations import verify_address_inplace
from app.errors import api_error
from app.response import success_object
from app.store import store
from app.utils import is_nonempty_str, logical_now_iso, new_id


bp = Blueprint("customers", __name__)


def _address_input_or_none(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise api_error("ERR_INVALID_REQUEST", "default_shipping_address must be object")
    return value


def _normalize_address(addr):
    if not isinstance(addr, dict):
        return None
    out = {
        "line1": addr.get("line1"),
        "line2": addr.get("line2"),
        "city": addr.get("city"),
        "region": addr.get("region"),
        "postal_code": addr.get("postal_code"),
        "country": addr.get("country"),
        "verified": False,  # forced
    }
    return out


@bp.route("/customers", methods=["POST"])
@require_role("Customer", "AdminOps")
def create_customer(user_id: str, role: str):
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    email = body.get("email")
    display_name = body.get("display_name")
    if not is_nonempty_str(email):
        raise api_error("ERR_INVALID_REQUEST", "email is required")
    if not is_nonempty_str(display_name):
        raise api_error("ERR_INVALID_REQUEST", "display_name is required")
    # Unique email
    for c in store.customers.values():
        if c.get("email") == email:
            raise api_error("ERR_INVALID_REQUEST", "email already in use")
    addr = _normalize_address(_address_input_or_none(body.get("default_shipping_address")))

    cid = new_id()
    now = logical_now_iso()
    cust = {
        "id": cid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "email": email,
        "display_name": display_name,
        "default_shipping_address": addr,
        "total_charged_cents": 0,
        "total_refunded_cents": 0,
    }
    store.customers[cid] = cust
    return success_object(cust, status=201)


@bp.route("/customers/<customer_id>", methods=["GET"])
@require_role("Customer", "AdminOps")
def get_customer(customer_id, user_id: str, role: str):
    cust = store.customers.get(customer_id)
    if not cust:
        raise api_error("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    assert_customer_owns(customer_id, user_id, role)
    return success_object(cust)


@bp.route("/customers/<customer_id>/shipping-address/verify", methods=["POST"])
@require_role("Customer")
def verify_customer_address(customer_id, user_id: str, role: str):
    cust = store.customers.get(customer_id)
    if not cust:
        raise api_error("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    assert_customer_owns(customer_id, user_id, role)
    if not cust.get("default_shipping_address"):
        raise api_error("ERR_ADDRESS_VERIFICATION_FAILED", "No address to verify")
    ok = verify_address_inplace(cust["default_shipping_address"])
    if not ok:
        raise api_error("ERR_ADDRESS_VERIFICATION_FAILED", "Address verification failed")
    cust["updated_at"] = logical_now_iso()
    cust["version"] = cust.get("version", 1) + 1
    return success_object(cust)
