"""Customer endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_object
from ..errors import ApiError
from ..ids import new_uuid
from ..serializers import customer_out
from ..validation import ensure_dict, require_num, require_str


bp = Blueprint("customers", __name__, url_prefix="/api")


@bp.post("/customers")
def register_customer():
    require_role("PlatformAdmin", "CustomerService")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    name = require_str(body, "name", max_len=120)
    phone = require_str(body, "phone")
    address = require_str(body, "address")
    lat = require_num(body, "lat", min_val=-90.0, max_val=90.0)
    lng = require_num(body, "lng", min_val=-180.0, max_val=180.0)
    with store.lock:
        if store.find_customer_by_phone(phone):
            raise ApiError("ERR_VALIDATION", "phone already in use")
        cid = new_uuid()
        now = store.now_iso()
        c = {
            "id": cid,
            "name": name,
            "phone": phone,
            "address": address,
            "lat": lat,
            "lng": lng,
            "credit_balance_cents": 0,
            "trust_score": 1.0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.customers[cid] = c
        return success_object(store.clock, customer_out(c), status=201)


@bp.get("/customers/<cid>")
def read_customer(cid: str):
    require_role("PlatformAdmin", "Customer", "CustomerService")
    store = g.store
    c = store.customers.get(cid)
    if not c:
        raise ApiError("ERR_NOT_FOUND")
    if g.user_role == "Customer" and g.user_id != cid:
        raise ApiError("ERR_FORBIDDEN")
    return success_object(store.clock, customer_out(c))
