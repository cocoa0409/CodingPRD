"""Customer registration, read, loyalty-ledger sub-resource."""
from flask import Blueprint, request
from db import DB
from errors import not_found
from middleware import (
    auth_context, require_role, require_customer_owner, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, created, ok_list
from services.common import stamp_common
from services.validation import require_email, require_fields, require_enum, require_string

bp = Blueprint("customers", __name__)

DELIVERY_ZONES = {"ZONE_A", "ZONE_B", "ZONE_C"}


@bp.post("/customers/register")
def register_customer():
    role, _ = auth_context()
    require_role(role, {"Anonymous"})
    payload = require_json()
    require_fields(payload, ["email", "full_name", "delivery_zone", "address_line"])
    email = require_email(payload, "email")
    full_name = require_string(payload, "full_name")
    delivery_zone = payload["delivery_zone"]
    require_enum(delivery_zone, DELIVERY_ZONES, "delivery_zone")
    address_line = require_string(payload, "address_line")

    entity = {
        **stamp_common(full=True),
        "email": email,
        "full_name": full_name,
        "delivery_zone": delivery_zone,
        "address_line": address_line,
        "loyalty_tier": "BRONZE",
        "points_balance": 0,
        "lifetime_points_earned": 0,
        "wallet_credit_cents": 0,
    }
    DB.customers[entity["id"]] = entity
    return created(entity)


@bp.get("/customers/<cid>")
def get_customer(cid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager", "ShopStaff"})
    entity = DB.customers.get(cid)
    if not entity:
        raise not_found("Customer")
    require_customer_owner(role, user_id, entity["id"])
    return ok(entity)


@bp.get("/customers/<cid>/loyalty-ledger")
def customer_loyalty_ledger(cid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    if cid not in DB.customers:
        raise not_found("Customer")
    require_customer_owner(role, user_id, cid)
    limit, offset = parse_pagination(request.args)
    rows = [r for r in DB.loyalty_ledger.values() if r["customer_id"] == cid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)
