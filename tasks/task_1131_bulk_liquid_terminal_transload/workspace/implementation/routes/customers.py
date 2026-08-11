"""Customer endpoints."""
from flask import Blueprint

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import customer_view
from validation import get_body, req_string, sort_and_page

bp = Blueprint("customers", __name__)

ANY_ROLE = ("TerminalManager", "TerminalOperator", "Scheduler", "Gauger",
            "QualityInspector", "BillingClerk", "CustomerRep")


@bp.post("/customers")
def create_customer():
    require_roles("TerminalManager")
    body = get_body()
    name = req_string(body, "name")
    contact_email = req_string(body, "contact_email")
    now = CLOCK.now()
    customer = {
        "id": new_id(),
        "name": name,
        "contact_email": contact_email,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.customers[customer["id"]] = customer
    return success_object(customer_view(customer), status=201)


@bp.get("/customers")
def list_customers():
    current_user()
    rows = list(STORE.customers.values())
    page, total, limit, offset = sort_and_page(rows)
    return success_list([customer_view(c) for c in page], total, limit, offset)


@bp.get("/customers/<customerId>")
def get_customer(customerId):
    current_user()
    customer = STORE.customers.get(customerId)
    if customer is None:
        raise err("ERR_CUSTOMER_NOT_FOUND", "Customer %s not found" % customerId)
    return success_object(customer_view(customer))
