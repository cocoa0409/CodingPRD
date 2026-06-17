"""Customer endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import domain, serializers

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = helpers.get_body()

    full_name = helpers.require_str(body, "full_name")
    email = helpers.require_str(body, "email")
    credit_score = helpers.require_int(body, "credit_score", minimum=300, maximum=850)
    monthly_income = helpers.require_int(body, "monthly_income_cents", minimum=0)
    existing_obligations = helpers.optional_int(
        body, "existing_monthly_obligations_cents", default=0, minimum=0)

    rec = {
        "full_name": full_name,
        "email": email,
        "credit_score": credit_score,
        "monthly_income_cents": monthly_income,
        "existing_monthly_obligations_cents": existing_obligations,
        "open_financing_count": 0,
    }
    helpers.stamp_create(rec)
    db.customers[rec["id"]] = rec
    return response.object_response(serializers.customer(rec), status=201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    # Customer may only fetch their own record.
    if role == "Customer" and user_id != cid:
        raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    rec = helpers.fetch(db.customers, cid)
    return response.object_response(serializers.customer(rec))


@bp.get("/customers/<cid>/orders")
def list_customer_orders(cid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    if role == "Customer" and user_id != cid:
        raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    helpers.fetch(db.customers, cid)
    limit, offset = helpers.get_pagination()
    rows = [o for o in db.orders.values() if o["customer_id"] == cid]
    page, total = helpers.paginate(rows, limit, offset)
    return response.array_response(
        [serializers.order(o) for o in page], limit, offset, total)


@bp.get("/customers/<cid>/financing-plans")
def list_customer_financing(cid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    if role == "Customer" and user_id != cid:
        raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    helpers.fetch(db.customers, cid)
    limit, offset = helpers.get_pagination()
    rows = [p for p in db.financing_plans.values() if p["customer_id"] == cid]
    page, total = helpers.paginate(rows, limit, offset)
    return response.array_response(
        [serializers.financing_plan(p) for p in page], limit, offset, total)
