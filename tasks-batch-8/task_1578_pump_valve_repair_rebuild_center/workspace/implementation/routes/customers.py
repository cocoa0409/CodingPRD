from flask import Blueprint, request

from db import DB, stamp_new
from errors import validation, not_found
from middleware import (
    as_bool,
    as_int,
    as_string,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object

bp = Blueprint("customers", __name__)

ALL_ROLES = [
    "ServiceManager",
    "IntakeCoordinator",
    "Inspector",
    "Technician",
    "Certifier",
    "Planner",
    "Customer",
]


def parse_pagination() -> tuple[int, int]:
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        validation("limit must be an integer")
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        validation("offset must be an integer")
    if limit < 1 or limit > 100:
        validation("limit must be between 1 and 100")
    if offset < 0:
        validation("offset must be >= 0")
    return limit, offset


@bp.route("/customers", methods=["POST"])
def create_customer():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["ServiceManager"])
    name = as_string(body, "name")
    account_number = as_string(body, "account_number")
    credit_limit_cents = as_int(body, "credit_limit_cents")
    warranty_terms_days = as_int(body, "warranty_terms_days")
    pool_program = as_bool(body, "pool_program", default=False)

    customer = stamp_new(
        {
            "name": name,
            "account_number": account_number,
            "credit_limit_cents": credit_limit_cents,
            "warranty_terms_days": warranty_terms_days,
            "pool_program": pool_program,
            "pool_available_count": 0,
        }
    )
    DB.customers[customer["id"]] = customer
    return success_object(customer, status=201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    authenticate()
    limit, offset = parse_pagination()
    items = sorted(DB.customers.values(), key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    caller = authenticate()
    customer = DB.customers.get(cid)
    if customer is None:
        not_found("Customer not found")
    require_customer_ownership(caller, customer["id"])
    return success_object(customer)
