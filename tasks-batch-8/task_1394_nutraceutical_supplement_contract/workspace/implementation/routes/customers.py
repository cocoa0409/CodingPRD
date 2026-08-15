"""Customer endpoints (PRD sections 3.1, 2.12)."""
from flask import Blueprint

from db import store, new_entity
from middleware import require_roles, ANY_ROLE
from response import ok
from util import body, req_str, not_found, paginate, sorted_by_created

bp = Blueprint("customers", __name__)


@bp.post("/api/customers")
@require_roles("ProductionPlanner")
def create_customer(user_id, role):
    data = body()
    brand_name = req_str(data, "brand_name")
    customer = new_entity({
        "brand_name": brand_name,
        "committed_order_value_cents": 0,
        "open_order_count": 0,
        "lifetime_receipts_cents": 0,
        "open_recall_count": 0,
    })
    store["customers"][customer["id"]] = customer
    return ok(customer, 201)


@bp.get("/api/customers/<customer_id>")
@require_roles(*ANY_ROLE)
def get_customer(user_id, role, customer_id):
    customer = store["customers"].get(customer_id)
    if customer is None:
        not_found()
    return ok(customer)


@bp.get("/api/customers/<customer_id>/formulas")
@require_roles(*ANY_ROLE)
def list_customer_formulas(user_id, role, customer_id):
    customer = store["customers"].get(customer_id)
    if customer is None:
        not_found()
    items = sorted_by_created(
        f for f in store["formulas"].values() if f["customer_id"] == customer_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)
