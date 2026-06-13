"""Customer registration, wallet, and loyalty tier projection (PRD §3.2)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, parse_pagination, paginate,
    serialize, serialize_list,
)
from services.pricing import tier_for_spend
from services.boutique_ledger import recompute_store_credit_outstanding

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate"})
    body = get_json_body()

    boutique_id = require_str(body, "boutique_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")

    get_or_404("boutique", boutique_id)

    # Email unique within the boutique (priority 16: ERR_DUPLICATE_KEY).
    for c in db.customers.values():
        if c["boutique_id"] == boutique_id and c["email"] == email:
            raise err(errors.ERR_DUPLICATE_KEY, "email already exists in this boutique")

    rec = stamp_new({
        "boutique_id": boutique_id,
        "full_name": full_name,
        "email": email,
        "status": "ACTIVE",
        "store_credit_cents": 0,
        "loyalty_points": 0,
        "captured_spend_cents": 0,
        "loyalty_tier": "STANDARD",
    })
    db.customers[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/customers/<rid>")
def get_customer(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("customer", rid)
    if role == "Customer" and user_id != rec["id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    return success(serialize(rec))


@bp.get("/customers")
def list_customers():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate"})
    limit, offset = parse_pagination()
    items = list(db.customers.values())
    boutique_id = request.args.get("boutique_id")
    if boutique_id is not None:
        items = [c for c in items if c["boutique_id"] == boutique_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.get("/customers/<rid>/tier-projection")
def tier_projection(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    customer = get_or_404("customer", rid)
    if role == "Customer" and user_id != customer["id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")

    pending = sum(
        o["total_cents"]
        for o in db.sales_orders.values()
        if o["customer_id"] == customer["id"] and o["payment_status"] == "AUTHORIZED"
    )
    projected_basis = customer["captured_spend_cents"] + pending
    return success({
        "actual_tier": customer["loyalty_tier"],
        "projected_tier": tier_for_spend(projected_basis),
        "projected_basis_cents": projected_basis,
    })


@bp.post("/customers/<rid>/store-credit-grants")
def grant_store_credit(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    customer = get_or_404("customer", rid)
    body = get_json_body()

    amount_cents = require_int(body, "amount_cents")
    if amount_cents < 0:
        raise err(errors.ERR_INVALID_REQUEST, "amount_cents must be >= 0")

    customer["store_credit_cents"] += amount_cents
    touch(customer)
    recompute_store_credit_outstanding(customer["boutique_id"])
    return success(serialize(customer), 201)
