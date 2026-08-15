"""Customers: onboarding, suspension lifecycle (PRD 3.1)."""
from flask import Blueprint, request

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from db import store
from errors import err
from respond import success
from serialize import ser_customer
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, opt_bool, paginate,
    reject_unknown, req_int, req_str, sorted_by_creation, touch,
)

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"name", "credit_limit_cents", "dedicated_program_enrolled"})
    name = req_str(data, "name")
    credit = req_int(data, "credit_limit_cents", minimum=0)
    enrolled = opt_bool(data, "dedicated_program_enrolled", False)
    c = {
        "id": new_id(),
        "_seq": next(store.seq),
        "name": name,
        "credit_limit_cents": credit,
        "dedicated_program_enrolled": enrolled,
        "status": "ACTIVE",
        "exposure_cents": 0,
    }
    c.update(new_common_fields())
    store.customers[c["id"]] = c
    return success(ser_customer(c), status=201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    require_roles(ALL_ROLES)
    status = request.args.get("status")
    items = [c for c in store.customers.values()
             if status is None or c["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_customer(c) for c in page],
                   response_type="array", pagination=pagination)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_roles(ALL_ROLES)
    return success(ser_customer(get_or_404(store.customers, "customers", cid)))


@bp.route("/customers/<cid>/suspend", methods=["POST"])
def suspend_customer(cid):
    require_roles([FLEET_ADMIN])
    c = get_or_404(store.customers, "customers", cid)
    reject_unknown(json_body(), set())
    if c["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_NOT_ACTIVE",
                  "Suspend requires the customer to be ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    return success(ser_customer(c))


@bp.route("/customers/<cid>/reactivate", methods=["POST"])
def reactivate_customer(cid):
    require_roles([FLEET_ADMIN])
    c = get_or_404(store.customers, "customers", cid)
    reject_unknown(json_body(), set())
    if c["status"] != "SUSPENDED":
        raise err("ERR_INVALID_REQUEST",
                  "Reactivate requires the customer to be SUSPENDED")
    c["status"] = "ACTIVE"
    touch(c)
    return success(ser_customer(c))
