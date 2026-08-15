"""Customer endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404

bp = Blueprint("customers", __name__)


@bp.post("/efficiency/customers")
def create_customer():
    require_roles({"ProgramManager"})
    body = get_body()
    customer = {
        "full_name": body.get("full_name"),
        "email": body.get("email"),
        "service_zip": body.get("service_zip"),
        "sector": body.get("sector"),
        "utility_account_id": body.get("utility_account_id"),
    }
    db.stamp_new(customer)
    db.customers[customer["id"]] = customer
    return success_object(customer, 201)


@bp.get("/efficiency/customers")
def list_customers():
    require_roles({"ProgramManager", "Contractor"})
    return paginate(list(db.customers.values()))


@bp.get("/efficiency/customers/<customer_id>")
def get_customer(customer_id):
    require_roles({"ProgramManager", "Contractor", "Customer"})
    return success_object(fetch_or_404(db.customers, customer_id, "Customer"))
