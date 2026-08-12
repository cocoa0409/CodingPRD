"""Customer endpoints."""

from flask import Blueprint

import db
from errors import ApiError, err_not_found, err_invalid_request, err_unauthorized
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import stamp_new, serialize

bp = Blueprint("customers", __name__)

READ_ROLES = ("PlatformAdmin", "SalesRep", "Assessor", "AssessmentReviewer",
              "FundingOfficer", "InstallCoordinator", "InventoryManager",
              "ClaimsAdjuster")


@bp.post("/stairlift-ops/customers")
def create_customer():
    require_role("PlatformAdmin", "SalesRep")
    body = get_json_body(["full_name", "date_of_birth", "home_region_code"])
    for f in ("full_name", "date_of_birth", "home_region_code"):
        if not isinstance(body[f], str):
            raise err_invalid_request(f"{f} must be a string")
    customer = {
        "full_name": body["full_name"],
        "date_of_birth": body["date_of_birth"],
        "home_region_code": body["home_region_code"],
        "status": "PROSPECT",
        "lifetime_outstanding_cents": 0,
    }
    stamp_new(customer)
    db.customers[customer["id"]] = customer
    return success_object(serialize(customer), 201)


@bp.get("/stairlift-ops/customers")
def list_customers():
    require_role(*READ_ROLES)
    limit, offset = get_pagination()
    status = None
    from flask import request
    status = request.args.get("status")
    items = sorted(db.customers.values(), key=lambda c: c["created_at"])
    if status:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.get("/stairlift-ops/customers/<cid>")
def get_customer(cid):
    user_id, role = require_role(*READ_ROLES, "Customer")
    customer = db.customers.get(cid)
    if customer is None:
        raise err_not_found("Customer not found")
    if role == "Customer" and user_id != cid:
        raise err_unauthorized()
    return success_object(serialize(customer))
