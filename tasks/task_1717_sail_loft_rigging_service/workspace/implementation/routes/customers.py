"""Customer endpoints."""

from flask import Blueprint

import db
import errors
import util
from middleware import require_roles
from response import success_object, success_list
from services import domain

bp = Blueprint("customers", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")


@bp.post("/lofts/customers")
def create_customer():
    require_roles("LoftManager")
    body = util.get_body()
    full_name = util.as_string(util.require_field(body, "full_name"), "full_name")
    email = util.as_string(util.require_field(body, "email"), "email")
    credit_limit_cents = util.as_int(util.require_field(body, "credit_limit_cents"), "credit_limit_cents")
    cust = util.stamp_new({
        "full_name": full_name,
        "email": email,
        "credit_limit_cents": credit_limit_cents,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    db.customers[cust["id"]] = cust
    return success_object(domain.serialize(cust), 201)


@bp.get("/lofts/customers")
def list_customers():
    require_roles("LoftManager", "Sailmaker", "Measurer", "Rigger")
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.customers.values()))
    items = util.filter_exact(items, "status", __import__("flask").request.args.get("status"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], limit, offset, total)


@bp.get("/lofts/customers/<customerId>")
def get_customer(customerId):
    require_roles(*READ_ROLES)
    cust = domain.get_customer_or_404(customerId)
    return success_object(domain.serialize(cust))


@bp.post("/lofts/customers/<customerId>/suspend")
def suspend_customer(customerId):
    require_roles("LoftManager")
    cust = domain.get_customer_or_404(customerId)
    if cust["status"] != "ACTIVE":
        raise errors.invalid_state(f"Customer must be ACTIVE to suspend (is {cust['status']})")
    if not (cust["outstanding_balance_cents"] > cust["credit_limit_cents"]):
        raise errors.account_rule_violation(
            "Suspension requires outstanding_balance_cents strictly greater than credit_limit_cents"
        )
    cust["status"] = "SUSPENDED"
    util.touch(cust)
    return success_object(domain.serialize(cust))


@bp.post("/lofts/customers/<customerId>/reinstate")
def reinstate_customer(customerId):
    require_roles("LoftManager")
    cust = domain.get_customer_or_404(customerId)
    if cust["status"] != "SUSPENDED":
        raise errors.invalid_state(f"Customer must be SUSPENDED to reinstate (is {cust['status']})")
    if not (cust["outstanding_balance_cents"] <= cust["credit_limit_cents"]):
        raise errors.account_rule_violation(
            "Reinstatement requires outstanding_balance_cents <= credit_limit_cents"
        )
    cust["status"] = "ACTIVE"
    util.touch(cust)
    return success_object(domain.serialize(cust))


@bp.post("/lofts/customers/<customerId>/close")
def close_customer(customerId):
    require_roles("LoftManager")
    cust = domain.get_customer_or_404(customerId)
    if cust["status"] != "ACTIVE":
        raise errors.invalid_state(f"Customer must be ACTIVE to close (is {cust['status']})")
    if cust["outstanding_balance_cents"] != 0:
        raise errors.account_rule_violation("Closure requires outstanding_balance_cents == 0")
    active_boats = [
        b for b in db.boats.values()
        if b["customer_id"] == cust["id"] and b["status"] == "ACTIVE"
    ]
    if active_boats:
        raise errors.account_rule_violation("Closure requires no boat in ACTIVE status")
    cust["status"] = "CLOSED"
    util.touch(cust)
    return success_object(domain.serialize(cust))


@bp.post("/lofts/customers/<customerId>/payments")
def record_payment(customerId):
    require_roles("LoftManager")
    cust = domain.get_customer_or_404(customerId)
    body = util.get_body()
    amount_cents = util.as_int(util.require_field(body, "amount_cents"), "amount_cents")
    new_balance = cust["outstanding_balance_cents"] - amount_cents
    cust["outstanding_balance_cents"] = max(0, new_balance)
    util.touch(cust)
    return success_object(domain.serialize(cust), 201)
