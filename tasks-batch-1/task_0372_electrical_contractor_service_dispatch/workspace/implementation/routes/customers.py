"""Customer endpoints (PRD §3.1).

Customer: full_name, email (unique), service_zip, phone.
"""
from flask import Blueprint

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_fields,
                     require_string, serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("customers", __name__)


@bp.post("/v1/customers")
def create_customer():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["full_name", "email", "service_zip", "phone"])
    require_string(body["full_name"], "full_name")
    require_string(body["email"], "email")
    require_string(body["service_zip"], "service_zip")
    require_string(body["phone"], "phone")

    # email unique across customers (ERR_DUPLICATE).
    for c in db.customers.values():
        if c["email"] == body["email"]:
            raise err("ERR_DUPLICATE", "A customer with this email already exists")

    record = {
        "full_name": body["full_name"],
        "email": body["email"],
        "service_zip": body["service_zip"],
        "phone": body["phone"],
    }
    db.stamp_new(record)
    db.customers[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/customers/<customer_id>")
def get_customer(customer_id):
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    record = db.customers.get(customer_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/customers")
def list_customers():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    limit, offset = parse_pagination()
    from flask import request
    email = request.args.get("email")

    items = list(db.customers.values())
    if email is not None:
        items = [c for c in items if c["email"] == email]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)
