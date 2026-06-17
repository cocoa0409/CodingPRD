"""Customer + condition photo + work-order list/fetch routes."""
from flask import Blueprint

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles
from helpers import (base_record, get_body, require_string, get_resource_or_404,
                     parse_pagination, paginate, serialize, serialize_list)
from response import ok_object, ok_array

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager"})
    body = get_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    phone = require_string(body, "phone")
    rec = base_record(common=True)
    rec.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "store_credit_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator", "Customer"})
    rec = get_resource_or_404(db.customers, cid)
    return ok_object(serialize(rec), 200)


@bp.get("/customers/<cid>/work-orders")
def list_customer_work_orders(cid):
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator", "Customer"})
    limit, offset = parse_pagination()
    get_resource_or_404(db.customers, cid)
    matches = [wo for wo in db.work_orders.values() if wo["customer_id"] == cid]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
