"""Customer endpoints (PRD 3.5)."""
from flask import Blueprint

from db import db
from errors import ApiError, ERR_CUSTOMER_NOT_FOUND
from middleware import get_body, req_str, require_roles
from response import success, serialize
from services import new_resource
from routes.listing import list_response

bp = Blueprint("customers", __name__)

ALL = ("Grower", "Chef", "OpsManager")


@bp.post("/customers")
@require_roles("OpsManager")
def create_customer():
    body = get_body()
    rec = new_resource(
        {
            "business_name": req_str(body, "business_name"),
            "contact_email": req_str(body, "contact_email"),
            "delivery_zone": req_str(body, "delivery_zone"),
            "credit_balance_cents": 0,
            "is_active": True,
        }
    )
    db.customers[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/customers")
@require_roles(*ALL)
def list_customers():
    return list_response(list(db.customers.values()))


@bp.get("/customers/<cid>")
@require_roles(*ALL)
def get_customer(cid):
    rec = db.customers.get(cid)
    if rec is None:
        raise ApiError(404, ERR_CUSTOMER_NOT_FOUND, "customer_id does not exist.")
    return success(serialize(rec), "object", 200)
