"""Customer endpoints."""

from flask import Blueprint

from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_enum, base_fields, paginate, err,
)
from response import success_object, success_list
from errors import ERR_CUSTOMER_NOT_FOUND

bp = Blueprint("customers", __name__)


def serialize_customer(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "customer_type": c["customer_type"],
        "email": c["email"],
        "phone": c["phone"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/api/customers")
def create_customer():
    require_role("OfficeAdmin")
    body = get_json_body()
    check_unknown_fields(body, {"name", "customer_type", "email", "phone"})
    require_fields(body, ["name", "customer_type", "email", "phone"])
    ctype = require_enum(body, "customer_type", {"RESIDENTIAL", "COMMERCIAL"})
    c = base_fields()
    c.update({
        "name": body["name"],
        "customer_type": ctype,
        "email": body["email"],
        "phone": body["phone"],
    })
    DB.customers[c["id"]] = c
    return success_object(serialize_customer(c), status=201)


@bp.get("/api/customers")
def list_customers():
    require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead")
    items = sorted(DB.customers.values(), key=lambda c: c["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_customer(c) for c in page], limit, offset, total)


@bp.get("/api/customers/<customerId>")
def get_customer(customerId):
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer")
    c = DB.customers.get(customerId)
    if c is None:
        raise err(ERR_CUSTOMER_NOT_FOUND, 404, "Customer id does not exist")
    if role == "Customer" and user_id != c["id"]:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise err(ERR_NOT_RESOURCE_OWNER, 403, "Customer acting on a resource owned by a different customer")
    return success_object(serialize_customer(c))
