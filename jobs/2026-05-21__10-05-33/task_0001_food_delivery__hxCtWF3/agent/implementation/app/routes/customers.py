"""Customer registration and lookup."""
from flask import request

from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..resource import stamp_new
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/customers", endpoint=f"{prefix}.create", view_func=create, methods=["POST"])
    app.add_url_rule("/api/customers/<cid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])


def _validate_coords(lat, lng):
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        raise fail("ERR_VALIDATION", "lat/lng must be numbers")
    if not (-90 <= lat_f <= 90) or not (-180 <= lng_f <= 180):
        raise fail("ERR_VALIDATION", "lat/lng out of range")
    return lat_f, lng_f


def create():
    parse_headers()
    require_role("PlatformAdmin", "CustomerService")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    phone = body.get("phone")
    address = body.get("address")
    if not isinstance(name, str) or not name.strip():
        raise fail("ERR_VALIDATION", "name required")
    if not isinstance(phone, str) or not phone.strip():
        raise fail("ERR_VALIDATION", "phone required")
    if phone in store.customer_phone:
        raise fail("ERR_VALIDATION", "phone already registered")
    if not isinstance(address, str) or not address.strip():
        raise fail("ERR_VALIDATION", "address required")
    lat, lng = _validate_coords(body.get("lat"), body.get("lng"))
    rec = stamp_new()
    rec.update({
        "name": name,
        "phone": phone,
        "address": address,
        "lat": lat,
        "lng": lng,
        "credit_balance_cents": 0,
        "trust_score": 1.0,
    })
    store.customers[rec["id"]] = rec
    store.customer_phone[phone] = rec["id"]
    return success(rec, status=201)


def read(cid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "Customer", "CustomerService")
    c = store.customers.get(cid)
    if not c:
        raise fail("ERR_NOT_FOUND")
    if role == "Customer" and user_id != c["id"]:
        raise fail("ERR_FORBIDDEN")
    return success(c)
