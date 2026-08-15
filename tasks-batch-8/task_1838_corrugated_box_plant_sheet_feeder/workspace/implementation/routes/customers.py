"""CustomerAccount endpoints."""
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import err_invalid_request, err_not_found
from middleware import require_roles
from response import success_object
from services.calcs import recompute_credit_exposure
from services.serialize import serialize_customer
from util import D, is_num, new_id, utcnow_iso
from ._helpers import get_json_body, require_fields

bp = Blueprint("customers", __name__)

ALL_ROLES = ("PlantAdmin", "SalesRep", "ProductionPlanner", "CustomerService", "ClaimsAdjuster", "Customer")


@bp.route("/api/customer-accounts", methods=["POST"])
@require_roles("SalesRep")
def create_customer(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["account_name", "ship_to_city", "distance_miles_from_plant", "credit_limit_dollars"])

    account_name = body["account_name"]
    ship_to_city = body["ship_to_city"]
    distance = body["distance_miles_from_plant"]
    credit_limit = body["credit_limit_dollars"]

    if not isinstance(account_name, str) or not account_name.strip():
        raise err_invalid_request("account_name must be a non-empty string")
    if not isinstance(ship_to_city, str) or not ship_to_city.strip():
        raise err_invalid_request("ship_to_city must be a non-empty string")
    if not is_num(distance) or D(distance) <= 0:
        raise err_invalid_request("distance_miles_from_plant must be > 0")
    if not is_num(credit_limit) or D(credit_limit) < 0:
        raise err_invalid_request("credit_limit_dollars must be >= 0")

    now = utcnow_iso()
    cid = new_id()
    cust = {
        "id": cid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "account_name": account_name,
        "ship_to_city": ship_to_city,
        "distance_miles_from_plant": D(distance),
        "credit_limit_dollars": D(credit_limit),
        "credit_exposure_dollars": Decimal("0.00"),
    }
    db.customer_accounts[cid] = cust
    return success_object(serialize_customer(cust), 201)


@bp.route("/api/customer-accounts/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_customer(cid, _user_id, _role):
    cust = db.customer_accounts.get(cid)
    if cust is None:
        raise err_not_found("customer account not found")
    return success_object(serialize_customer(cust), 200)
