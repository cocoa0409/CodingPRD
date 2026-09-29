"""Customer accounts and the regrind credit ledger (PRD 3.8)."""

from flask import Blueprint

import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("customers", __name__)

CREATORS = ["ProductionPlanner", "ApplicationEngineer"]
READ_ONE_ROLES = ["ProductionPlanner", "ApplicationEngineer", "QualityApprover", "Customer"]
READ_MANY_ROLES = ["ProductionPlanner", "ApplicationEngineer", "QualityApprover"]
OWNER = ["ProductionPlanner"]


@bp.route("/tooling/customers", methods=["POST"])
def create():
    authenticate(CREATORS)
    payload = v.body(
        required=("customer_code", "name", "tier"), optional=("regrind_credit_cents",)
    )
    customer_code = v.as_string(payload, "customer_code")
    name = v.as_string(payload, "name")
    tier = v.as_enum(payload, "tier", c.TIERS)
    credit = v.as_int(payload, "regrind_credit_cents", default=0)

    derive.require_unique("customers", "customer_code", customer_code)

    row = db.new_row(
        {
            "customer_code": customer_code,
            "name": name,
            "tier": tier,
            "account_status": "ACTIVE",
            "regrind_credit_cents": credit,
        }
    )
    db.customers[row["id"]] = row
    return object_response(serialize.customer(row), 201)


@bp.route("/tooling/customers", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "customers",
        READ_MANY_ROLES,
        {"tier": c.TIERS, "account_status": c.ACCOUNT_STATUSES},
    )
    return c.list_response("customers", rows, limit, offset)


@bp.route("/tooling/customers/<customer_id>", methods=["GET"])
def read(customer_id):
    user_id, role = authenticate(READ_ONE_ROLES)
    v.pagination()
    customer = derive.must_exist("customers", customer_id)
    if role == "Customer" and customer["id"] != user_id:
        raise ApiError(
            "ERR_CUSTOMER_SCOPE_VIOLATION",
            "A Customer caller may read only its own account.",
        )
    return object_response(serialize.customer(customer))


@bp.route("/tooling/customers/<customer_id>/credit-adjustments", methods=["POST"])
def credit_adjustment(customer_id):
    authenticate(OWNER)
    payload = v.body(required=("delta_cents", "reason"))
    delta = v.as_int(payload, "delta_cents")
    v.as_string(payload, "reason")

    customer = derive.must_exist("customers", customer_id)
    if customer["account_status"] not in ("ACTIVE", "CREDIT_HOLD"):
        raise ApiError(
            "ERR_INVALID_CUSTOMER_STATE",
            "A CLOSED account cannot take credit adjustments.",
        )

    derive.apply_credit_movement(customer, delta, allow_resume=True)
    db.touch(customer)
    return object_response(serialize.customer(customer))


@bp.route("/tooling/customers/<customer_id>/close", methods=["POST"])
def close(customer_id):
    authenticate(OWNER)
    payload = v.body(required=("close_reason",))
    v.as_string(payload, "close_reason")

    customer = derive.must_exist("customers", customer_id)
    if customer["account_status"] not in ("ACTIVE", "CREDIT_HOLD"):
        raise ApiError(
            "ERR_INVALID_CUSTOMER_STATE", "The account is already CLOSED."
        )
    if derive.customer_has_open_work(customer):
        raise ApiError(
            "ERR_OPEN_DEMAND_EXISTS",
            "Outstanding orders or reconditioning jobs must be settled first.",
        )

    customer["account_status"] = "CLOSED"
    db.touch(customer)
    return object_response(serialize.customer(customer))
