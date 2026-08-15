from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_CUSTOMER_ON_CREDIT_HOLD, ERR_RIGHT_NOT_ACTIVE,
    ERR_RIGHT_NOT_SUSPENDED, not_found,
)
from helpers import (
    get_body, list_query, new_entity, ser_right, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import adjust_exposure

bp = Blueprint("rights", __name__)

_ROLES = ["PlatformAdmin", "AllocationManager", "TerminalOperator", "ContractAdministrator"]


def _get_right(right_id):
    r = db.lifting_rights.get(right_id)
    if r is None:
        raise not_found("LiftingRight {} does not exist".format(right_id))
    return r


@bp.post("/rack/lifting-rights")
def create_right():
    require_roles(["AllocationManager"])
    body = get_body()
    for fk, coll, label in (
        ("customer_id", db.customers, "Customer"),
        ("terminal_id", db.terminals, "Terminal"),
        ("product_id", db.products, "Product"),
        ("contract_id", db.supply_contracts, "SupplyContract"),
    ):
        if body.get(fk) not in coll:
            raise not_found("{} {} does not exist".format(label, body.get(fk)))
    r = new_entity({
        "customer_id": body.get("customer_id"),
        "terminal_id": body.get("terminal_id"),
        "product_id": body.get("product_id"),
        "contract_id": body.get("contract_id"),
        "daily_ratable_gallons": body.get("daily_ratable_gallons", 0),
        "lifted_today_gallons": 0,
        "reserved_gallons": 0,
        "allocated_gallons": 0,
        "status": "ACTIVE",
    })
    db.lifting_rights[r["id"]] = r
    return success_object(ser_right(r), 201)


@bp.get("/rack/lifting-rights/<rightId>")
def get_right(rightId):
    require_roles(_ROLES)
    return success_object(ser_right(_get_right(rightId)))


@bp.get("/rack/lifting-rights")
def list_rights():
    require_roles(_ROLES)
    page, total, limit, offset = list_query(
        db.lifting_rights.values(), request.args,
        ["customer_id", "terminal_id", "product_id", "contract_id", "status"],
    )
    return success_list([ser_right(r) for r in page], total, limit, offset)


@bp.post("/rack/lifting-rights/<rightId>/suspend")
def suspend_right(rightId):
    require_roles(["AllocationManager"])
    r = _get_right(rightId)
    if r["status"] != "ACTIVE":
        raise ApiError(
            ERR_RIGHT_NOT_ACTIVE, 409,
            "LiftingRight must be ACTIVE to suspend",
        )
    # Cascade: every RESERVED ticket of this right is cancelled; its gallons
    # leave the right's reserved pool and its gross leaves the exposure.
    customer = db.customers.get(r["customer_id"])
    credit_back = 0
    for t in list(db.lifting_tickets.values()):
        if t["lifting_right_id"] == r["id"] and t["status"] == "RESERVED":
            r["reserved_gallons"] -= t["requested_gallons"]
            credit_back += t["gross_cents"]
            t["status"] = "CANCELLED"
            touch(t)
    if credit_back and customer is not None:
        adjust_exposure(customer, -credit_back)
    r["status"] = "SUSPENDED"
    touch(r)
    return success_object(ser_right(r))


@bp.post("/rack/lifting-rights/<rightId>/reinstate")
def reinstate_right(rightId):
    require_roles(["AllocationManager"])
    r = _get_right(rightId)
    if r["status"] != "SUSPENDED":
        raise ApiError(
            ERR_RIGHT_NOT_SUSPENDED, 409,
            "LiftingRight must be SUSPENDED to reinstate",
        )
    customer = db.customers.get(r["customer_id"])
    if customer is not None and customer["credit_status"] != "GOOD":
        raise ApiError(
            ERR_CUSTOMER_ON_CREDIT_HOLD, 402,
            "Customer is on credit hold; reinstatement refused",
        )
    r["status"] = "ACTIVE"
    touch(r)
    return success_object(ser_right(r))
