"""Customer endpoints (PRD §3.1, SCAFFOLD §1.5)."""
from flask import Blueprint, request

import db
from errors import err, ERR_CUSTOMER_NOT_FOUND, ERR_INVALID_ORDER_STATE, ERR_FORBIDDEN_ROLE, ERR_VALIDATION
from middleware import get_user_context, require_role
import validate as V
from timeutil import parse_iso
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("customers", __name__)


@bp.route("/v1/customers", methods=["POST"])
def create_customer():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin"})  # PRD §4: PlatformAdmin only
    body = V.get_body()
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")
    dob = V.require_str(body, "date_of_birth")
    try:
        parse_iso(dob)
    except ValueError:
        err(ERR_VALIDATION, "date_of_birth must be an ISO 8601 date")
    snap_balance = V.opt_int(body, "snap_ebt_balance_cents", 0, minimum=0)  # default 0
    with db.lock:
        customer = {
            "email": email,
            "full_name": full_name,
            "date_of_birth": dob,
            "snap_ebt_balance_cents": snap_balance,
            "status": "ACTIVE",  # PRD §3.1: begins ACTIVE
        }
        db.stamp_create(customer)
        db.customers[customer["id"]] = customer
        return object_response(public(customer), 201)


@bp.route("/v1/customers", methods=["GET"])
def list_customers():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps"})  # PRD §4
    limit, offset = get_pagination()
    email = request.args.get("email")
    with db.lock:
        records = list(db.customers.values())
        if email is not None:
            records = [c for c in records if c["email"] == email]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    with db.lock:
        customer = db.customers.get(customer_id)
        if customer is None:
            err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
        # Entity-backed ownership: a Customer may only read their own record.
        if role == "Customer" and user_id != customer_id:
            err(ERR_FORBIDDEN_ROLE, "Customer may only access their own record")
        return object_response(public(customer))


@bp.route("/v1/customers/<customer_id>/suspend", methods=["POST"])
def suspend_customer(customer_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin"})  # PRD §4
    with db.lock:
        customer = db.customers.get(customer_id)
        if customer is None:
            err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
        if customer["status"] != "ACTIVE":
            err(ERR_INVALID_ORDER_STATE, "Customer is not ACTIVE")
        customer["status"] = "SUSPENDED"
        db.touch(customer)
        return object_response(public(customer))


@bp.route("/v1/customers/<customer_id>/reinstate", methods=["POST"])
def reinstate_customer(customer_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin"})  # PRD §4
    with db.lock:
        customer = db.customers.get(customer_id)
        if customer is None:
            err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
        if customer["status"] != "SUSPENDED":
            err(ERR_INVALID_ORDER_STATE, "Customer is not SUSPENDED")
        customer["status"] = "ACTIVE"
        db.touch(customer)
        return object_response(public(customer))
