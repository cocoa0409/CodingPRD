from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_CUSTOMER_NOT_FOUND, ERR_DUPLICATE_CODE, \
    ERR_INVALID_STATE, ERR_CROSS_CUSTOMER_ACCESS
from services import stamp_new, touch, ser_customer, ser_bottle_spec, \
    sorted_rows, cancel_order
from util import new_id
from validate import get_body, check_fields, pagination_params, query_filter

bp = Blueprint("customers", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "ProductionScheduler", "LogisticsCoordinator",
              "CustomerQualityRep"]

SPEC_STATUSES = {"DRAFT", "SUBMITTED", "IN_QUALIFICATION",
                 "REVISION_REQUESTED", "QUALIFIED", "PRODUCTION_ACTIVE",
                 "RETIRED"}


def get_customer_or_404(customer_id):
    c = store.customers.get(customer_id)
    if c is None:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer id does not resolve")
    return c


@bp.post("/customers")
def create_customer():
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    body = check_fields(get_body(), {
        "name": ("str", True),
        "customer_code": ("str", True),
        "credit_limit_cents": ("int", True),
        "default_logistics_mode": ("enum", False,
                                   {"WAREHOUSE", "BLOW_ON_SITE"}),
    })
    for c in store.customers.values():
        if c["customer_code"] == body["customer_code"]:
            raise_err(ERR_DUPLICATE_CODE, "customer_code must be unique")
    customer = {
        "name": body["name"],
        "customer_code": body["customer_code"],
        "credit_limit_cents": body["credit_limit_cents"],
        "default_logistics_mode": body.get("default_logistics_mode", "WAREHOUSE"),
        "status": "ACTIVE",
    }
    stamp_new(customer, new_id())
    store.customers[customer["id"]] = customer
    return success_object(ser_customer(customer), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    customer = get_customer_or_404(cid)
    return success_object(ser_customer(customer))


@bp.post("/customers/<cid>/suspend")
def suspend_customer(cid):
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    check_fields(get_body(), {})  # no input fields; reject unknown keys
    customer = get_customer_or_404(cid)
    if customer["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE customer can be suspended")
    customer["status"] = "SUSPENDED"
    touch(customer)
    # cascade: cancel every order still DRAFT/SCHEDULED/RELEASED/HELD and
    # their CONFIRMED/IN_PROGRESS slots; RUNNING orders are left to finish
    for o in list(store.production_orders.values()):
        if (o["customer_id"] == customer["id"]
                and o["status"] in ("DRAFT", "SCHEDULED", "RELEASED", "HELD")):
            cancel_order(o)
    return success_object(ser_customer(customer))


@bp.post("/customers/<cid>/reactivate")
def reactivate_customer(cid):
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    check_fields(get_body(), {})
    customer = get_customer_or_404(cid)
    if customer["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE,
                  "Only a SUSPENDED customer can be reactivated")
    customer["status"] = "ACTIVE"
    touch(customer)
    return success_object(ser_customer(customer))


@bp.get("/customers/<cid>/bottle-specs")
def list_customer_specs(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    # CustomerQualityRep may list only its own customer's specs
    if role == "CustomerQualityRep" and user_id != cid:
        raise_err(ERR_CROSS_CUSTOMER_ACCESS,
                  "CustomerQualityRep may act only on its own customer")
    get_customer_or_404(cid)
    status = query_filter("status", SPEC_STATUSES)
    limit, offset = pagination_params()
    rows = [s for s in store.bottle_specs.values() if s["customer_id"] == cid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_bottle_spec(s) for s in page], limit, offset,
                        len(rows))
