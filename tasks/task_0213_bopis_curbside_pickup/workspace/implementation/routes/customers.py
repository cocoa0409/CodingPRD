"""Customer endpoints."""

from flask import Blueprint, request

from db import db, stamp_common
from errors import err
from middleware import require_auth, get_json_body
from response import object_response, array_response
from services.common import (
    require_str, get_or_404, parse_pagination, paginate,
    ser_customer, ser_order,
)

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    # Anonymous self-registration is exempt from authentication (PRD §2.1).
    # No header presence check; but if a role IS supplied it must be permitted.
    role = request.headers.get("X-User-Role")
    if role is not None and role not in {"Anonymous", "PlatformAdmin"}:
        raise err("ERR_UNAUTHORIZED",
                  "role %s is not permitted for this endpoint" % role)
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone")

    # email unique among customers
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already registered")

    rec = {
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "no_show_strikes": 0,
        "pickup_standing": "GOOD",
    }
    stamp_common(rec)
    db.customers[rec["id"]] = rec
    return object_response(ser_customer(rec), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    require_auth({"Customer", "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.customers, cid)
    return object_response(ser_customer(rec))


@bp.get("/customers/<cid>/orders")
def list_customer_orders(cid):
    require_auth({"Customer", "StoreManager", "PlatformAdmin"})
    get_or_404(db.customers, cid)
    limit, offset = parse_pagination(request.args)
    items = [o for o in db.orders.values() if o["customer_id"] == cid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_order(o) for o in page], limit, offset, total)
