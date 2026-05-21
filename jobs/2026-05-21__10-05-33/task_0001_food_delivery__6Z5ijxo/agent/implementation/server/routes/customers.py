from flask import Blueprint

from ..auth import require_role
from ..envelope import success, created
from ..errors import err
from ..repository import base_versioned, body_or_empty
from ..store import store

bp = Blueprint("customers", __name__)


def _view(c):
    return {k: c[k] for k in ("id", "name", "phone", "address", "lat", "lng",
                              "credit_balance_cents", "trust_score",
                              "created_at", "updated_at", "version")}


@bp.post("/api/customers")
def register_customer():
    require_role("PlatformAdmin", "CustomerService")
    body = body_or_empty()
    name = body.get("name")
    phone = body.get("phone")
    address = body.get("address")
    lat = body.get("lat")
    lng = body.get("lng")
    if not isinstance(name, str) or not name.strip():
        raise err("ERR_VALIDATION", "name required")
    if not isinstance(phone, str) or not phone.strip():
        raise err("ERR_VALIDATION", "phone required")
    if not isinstance(address, str) or not address.strip():
        raise err("ERR_VALIDATION", "address required")
    if not isinstance(lat, (int, float)) or isinstance(lat, bool) or lat < -90 or lat > 90:
        raise err("ERR_VALIDATION", "lat invalid")
    if not isinstance(lng, (int, float)) or isinstance(lng, bool) or lng < -180 or lng > 180:
        raise err("ERR_VALIDATION", "lng invalid")
    for c in store.customers.values():
        if c["phone"] == phone:
            raise err("ERR_VALIDATION", "phone already in use")
    c = base_versioned()
    c.update({
        "name": name,
        "phone": phone,
        "address": address,
        "lat": float(lat),
        "lng": float(lng),
        "credit_balance_cents": 0,
        "trust_score": 1.0,
    })
    store.customers[c["id"]] = c
    return created(_view(c))


@bp.get("/api/customers/<cid>")
def get_customer(cid):
    uid, role = require_role("PlatformAdmin", "Customer", "CustomerService")
    c = store.customers.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "customer not found")
    if role == "Customer" and c["id"] != uid:
        raise err("ERR_FORBIDDEN", "not the same customer")
    return success(_view(c))
