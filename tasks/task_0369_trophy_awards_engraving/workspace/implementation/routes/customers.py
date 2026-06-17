from flask import Blueprint, request
from db import db
from errors import err
from response import ok, ok_list
from middleware import authenticate, require_role, KNOWN_ROLES
from services import serialize
from services.common import (
    get_json_body, stamp_create, paginate, page_slice,
    require_fields, is_str,
)

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    # Open to Anonymous and ShopManager; auth headers are NOT required here.
    # If a role header is supplied, it must be one allowed to register.
    role = request.headers.get("X-User-Role")
    if role is not None:
        if role not in KNOWN_ROLES:
            raise err("ERR_UNAUTHENTICATED", "Unknown role")
        if role not in ("Anonymous", "ShopManager"):
            raise err("ERR_FORBIDDEN", "Role not permitted to register a customer")

    body = get_json_body()
    require_fields(body, ["email", "full_name"])
    email = body["email"]
    full_name = body["full_name"]
    org_name = body.get("org_name")
    if not is_str(email) or not email.strip():
        raise err("ERR_INVALID_REQUEST", "email must be a non-empty string")
    if not is_str(full_name):
        raise err("ERR_INVALID_REQUEST", "full_name must be a string")
    if org_name is not None and not is_str(org_name):
        raise err("ERR_INVALID_REQUEST", "org_name must be a string")

    # unique email
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE_VALUE", "A customer with this email already exists")

    rec = {
        "email": email,
        "full_name": full_name,
        "org_name": org_name,
        "lifetime_completed_orders": 0,
        "on_time_rate_pct": None,
    }
    stamp_create(rec)
    db.customers[rec["id"]] = rec
    return ok(serialize.customer(rec), 201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    rec = db.customers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    return ok(serialize.customer(rec))


@bp.route("/customers/<cid>/orders", methods=["GET"])
def list_customer_orders(cid):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    rec = db.customers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    if caller.role == "Customer" and caller.user_id != cid:
        raise err("ERR_FORBIDDEN", "Customers may only list their own orders")
    limit, offset = paginate()
    items = [o for o in db.orders.values() if o["customer_id"] == cid]
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.order(o) for o in page], limit, offset, total)
