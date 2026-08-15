"""Customer endpoints."""
from flask import Blueprint

from db import store
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    raise_err,
)
from helpers import (
    body_json,
    check_boolean,
    check_enum,
    check_string,
    get_or_404,
    paginate,
    parse_pagination,
    stamp_new,
    touch,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import customer_view

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    user_id, role = require_roles({"ShopManager"})
    data = body_json()
    company_name = check_string(data, "company_name", required=True)
    priority_tier = check_enum(data, "priority_tier", {"STANDARD", "PREFERRED"}, required=False, default="STANDARD")
    credit_hold = check_boolean(data, "credit_hold", required=False, default=False)
    status = check_enum(data, "status", {"ACTIVE", "SUSPENDED"}, required=False, default="ACTIVE")

    customer = stamp_new({
        "company_name": company_name,
        "priority_tier": priority_tier,
        "credit_hold": credit_hold,
        "status": status,
    })
    store.customers[customer["id"]] = customer
    return success_object(customer_view(customer), status=201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    user_id, role = require_roles(
        {"Customer", "LineOperator", "LabChemist", "QCInspector", "EHSOfficer", "ShopManager"}
    )
    limit, offset = parse_pagination()
    items = sorted(store.customers.values(), key=lambda c: (c["created_at"], c["id"]))
    if role == "Customer":
        items = [c for c in items if c["id"] == user_id]
    page, total = paginate(items, limit, offset)
    return success_list([customer_view(c) for c in page], limit, offset, total)


@bp.route("/customers/<customer_id>", methods=["PATCH"])
def patch_customer(customer_id):
    user_id, role = require_roles({"ShopManager"})
    # Tier 4: existence
    customer = store.customers.get(customer_id)
    if customer is None:
        raise_err(ERR_NOT_FOUND, "customer not found")
    # Tier 5: schema
    data = body_json()
    if "credit_hold" in data and not isinstance(data["credit_hold"], bool):
        raise_err(ERR_INVALID_REQUEST, "credit_hold must be a boolean")
    if "status" in data and data["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_REQUEST, "status must be ACTIVE or SUSPENDED")
    if "priority_tier" in data and data["priority_tier"] not in ("STANDARD", "PREFERRED"):
        raise_err(ERR_INVALID_REQUEST, "priority_tier must be STANDARD or PREFERRED")

    if "credit_hold" in data:
        customer["credit_hold"] = data["credit_hold"]
    if "status" in data:
        customer["status"] = data["status"]
    if "priority_tier" in data:
        customer["priority_tier"] = data["priority_tier"]
    touch(customer)
    return success_object(customer_view(customer))
