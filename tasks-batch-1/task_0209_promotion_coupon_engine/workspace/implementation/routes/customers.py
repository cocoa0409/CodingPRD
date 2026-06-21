"""Customer endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
)

bp = Blueprint("customers", __name__)


def _serialize_customer(c):
    return serialize(c)


@bp.post("/customers")
@require_roles("MerchantAdmin", "Shopper")
def create_customer():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        email = require_str(body, "email")
        display_name = require_str(body, "display_name")
        # Uniqueness: email case-insensitive (priority 6).
        for c in db.customers.values():
            if c["email"].lower() == email.lower():
                raise err("ERR_DUPLICATE", "Customer email already exists")
        rec = new_record(
            {
                "email": email,
                "display_name": display_name,
                "order_count": 0,
                "lifetime_discount_cents": 0,
            }
        )
        db.customers[rec["id"]] = rec
        return success(_serialize_customer(rec), 201)


@bp.get("/customers/<customer_id>")
@require_roles("MerchantAdmin", "Shopper")
def get_customer(customer_id):
    with db.lock:
        c = db.customers.get(customer_id)
        if not c:
            raise err("ERR_NOT_FOUND", "Customer not found")
        return success(_serialize_customer(c), 200)


@bp.get("/customers")
@require_roles("MerchantAdmin")
def list_customers():
    with db.lock:
        limit, offset = paginate(request.args)
        email = request.args.get("email")
        items = list(db.customers.values())
        if email is not None:
            items = [c for c in items if c["email"].lower() == email.lower()]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list(
            [_serialize_customer(c) for c in page], limit, offset, total
        )
