"""Customer endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_role
from ..envelope import envelope_object, expect_json_body
from ..errors import ApiError
from ..ids import new_uuid
from ..store import get_clock, get_store
from ..validators import req_number, req_str

bp = Blueprint("customers", __name__, url_prefix="/api")


def _ensure_customer(store, cid):
    rec = store.customers.get(cid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Customer {cid} not found")
    return rec


@bp.post("/customers")
def register_customer():
    require_role({"PlatformAdmin", "CustomerService"})
    body = expect_json_body()
    name = req_str(body, "name").strip()
    phone = req_str(body, "phone").strip()
    address = req_str(body, "address")
    lat = req_number(body, "lat")
    lng = req_number(body, "lng")
    if not name or not phone:
        raise ApiError("ERR_VALIDATION", "name/phone required")
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ApiError("ERR_VALIDATION", "lat/lng out of range")
    store = get_store()
    clock = get_clock()
    with store.lock:
        if phone in store.customer_phones:
            raise ApiError("ERR_VALIDATION", "customer phone already in use")
        now = clock.now_iso()
        rec = {
            "id": new_uuid(),
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
        store.customers[rec["id"]] = rec
        store.customer_phones.add(phone)
    return envelope_object(rec, status=201)


@bp.get("/customers/<cid>")
def read_customer(cid):
    uid, role = require_role({"PlatformAdmin", "Customer", "CustomerService"})
    store = get_store()
    with store.lock:
        rec = _ensure_customer(store, cid)
        if role == "Customer" and uid != rec["id"]:
            raise ApiError("ERR_FORBIDDEN", "Customer may only read self")
    return envelope_object(rec)
