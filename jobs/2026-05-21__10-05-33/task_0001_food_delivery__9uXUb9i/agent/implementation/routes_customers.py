"""Customer endpoints."""
from __future__ import annotations

from flask import Blueprint, g

from auth import require_roles
from common import get_json_body, require_str, require_number, validate_lat_lng
from envelope import success
from errors import ApiError
from serializers import serialize_customer
import store
from store import gen_id, iso_z, lock, now


bp = Blueprint("customers", __name__, url_prefix="/api/customers")


def _find_customer(cid: str) -> dict:
    c = store.customers.get(cid)
    if not c:
        raise ApiError("ERR_NOT_FOUND", "Customer not found.")
    return c


@bp.post("")
@require_roles("PlatformAdmin", "CustomerService")
def register_customer():
    body = get_json_body()
    name = require_str(body, "name", max_len=120)
    phone = require_str(body, "phone", max_len=40)
    address = require_str(body, "address")
    lat = require_number(body, "lat")
    lng = require_number(body, "lng")
    validate_lat_lng(lat, lng)

    with lock():
        for c in store.customers.values():
            if c["phone"] == phone:
                raise ApiError("ERR_VALIDATION", "Phone must be unique across customers.")
        t = now()
        cid = gen_id()
        rec = {
            "id": cid,
            "name": name,
            "phone": phone,
            "address": address,
            "lat": lat,
            "lng": lng,
            "credit_balance_cents": 0,
            "trust_score": 1.0,
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
        store.customers[cid] = rec
    return success(serialize_customer(rec), status=201)


@bp.get("/<cid>")
@require_roles("PlatformAdmin", "Customer", "CustomerService")
def read_customer(cid: str):
    c = _find_customer(cid)
    if g.role == "Customer" and g.user_id != c["id"]:
        raise ApiError("ERR_FORBIDDEN", "Customer identity mismatch.")
    return success(serialize_customer(c))
