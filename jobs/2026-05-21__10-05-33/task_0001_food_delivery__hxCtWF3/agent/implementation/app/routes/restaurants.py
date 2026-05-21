"""Restaurant lifecycle endpoints."""
from flask import request

from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..pagination import parse_pagination, window
from ..resource import stamp_new, bump, check_occ
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/restaurants", endpoint=f"{prefix}.create", view_func=create, methods=["POST"])
    app.add_url_rule("/api/restaurants", endpoint=f"{prefix}.list", view_func=list_restaurants, methods=["GET"])
    app.add_url_rule("/api/restaurants/<rid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])
    app.add_url_rule("/api/restaurants/<rid>", endpoint=f"{prefix}.update", view_func=update, methods=["PATCH"])
    app.add_url_rule("/api/restaurants/<rid>/approve", endpoint=f"{prefix}.approve", view_func=approve, methods=["POST"])
    app.add_url_rule("/api/restaurants/<rid>/suspend", endpoint=f"{prefix}.suspend", view_func=suspend, methods=["POST"])
    app.add_url_rule("/api/restaurants/<rid>/reinstate", endpoint=f"{prefix}.reinstate", view_func=reinstate, methods=["POST"])
    app.add_url_rule("/api/restaurants/<rid>/settle", endpoint=f"{prefix}.settle", view_func=settle, methods=["POST"])


def _validate_rate(rate):
    if rate is None:
        return None
    try:
        v = float(rate)
    except (TypeError, ValueError):
        raise fail("ERR_VALIDATION", "commission_rate_override must be a number")
    if v < 0.05 or v > 0.35:
        raise fail("ERR_VALIDATION", "commission_rate_override out of range")
    return v


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
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise fail("ERR_VALIDATION", "name required, 1..120 chars")
    # name uniqueness amongst non-CLOSED restaurants
    for r in store.restaurants.values():
        if r["status"] != "CLOSED" and r["name"] == name:
            raise fail("ERR_VALIDATION", "restaurant name must be unique among active restaurants")
    address = body.get("address")
    if not isinstance(address, str) or not address.strip():
        raise fail("ERR_VALIDATION", "address required")
    lat, lng = _validate_coords(body.get("lat"), body.get("lng"))
    rate = _validate_rate(body.get("commission_rate_override"))
    rec = stamp_new()
    rec.update({
        "name": name,
        "address": address,
        "lat": lat,
        "lng": lng,
        "status": "PENDING_APPROVAL",
        "commission_rate_override": rate,
        "pending_settlement_cents": 0,
    })
    store.restaurants[rec["id"]] = rec
    return success(rec, status=201)


def list_restaurants():
    parse_headers()
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    rows = [r for r in store.restaurants.values()
            if status_filter is None or r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = window(rows, limit, offset)
    return success(page, page=meta, response_type="array")


def _load(rid):
    r = store.restaurants.get(rid)
    if not r:
        raise fail("ERR_NOT_FOUND")
    return r


def read(rid):
    parse_headers()
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    r = _load(rid)
    return success(r)


def update(rid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "Restaurant")
    r = _load(rid)
    if role == "Restaurant" and user_id != r["id"]:
        raise fail("ERR_FORBIDDEN")
    body = request.get_json(silent=True) or {}
    check_occ(r, body)
    if "address" in body:
        if not isinstance(body["address"], str) or not body["address"].strip():
            raise fail("ERR_VALIDATION", "address must be non-empty string")
        r["address"] = body["address"]
    if "lat" in body or "lng" in body:
        lat = body["lat"] if "lat" in body else r["lat"]
        lng = body["lng"] if "lng" in body else r["lng"]
        r["lat"], r["lng"] = _validate_coords(lat, lng)
    if "commission_rate_override" in body:
        r["commission_rate_override"] = _validate_rate(body["commission_rate_override"])
    if "name" in body and body["name"] != r["name"]:
        raise fail("ERR_VALIDATION", "name is immutable")
    bump(r)
    return success(r)


def approve(rid):
    parse_headers()
    require_role("PlatformAdmin")
    r = _load(rid)
    if r["status"] != "PENDING_APPROVAL":
        raise fail("ERR_INVALID_STATE")
    r["status"] = "ACTIVE"
    bump(r)
    return success(r)


def suspend(rid):
    parse_headers()
    require_role("PlatformAdmin")
    r = _load(rid)
    if r["status"] != "ACTIVE":
        raise fail("ERR_INVALID_STATE")
    r["status"] = "SUSPENDED"
    bump(r)
    # Cascade: any PLACED orders for this restaurant become CANCELLED + payment VOIDED.
    from ..clock import format_iso
    from ..server import clock
    now = format_iso(clock.now())
    for o in store.orders.values():
        if o["restaurant_id"] == r["id"] and o["status"] == "PLACED":
            o["status"] = "CANCELLED"
            o["payment_status"] = "VOIDED"
            o["updated_at"] = now
            o["version"] += 1
    return success(r)


def reinstate(rid):
    parse_headers()
    require_role("PlatformAdmin")
    r = _load(rid)
    if r["status"] != "SUSPENDED":
        raise fail("ERR_INVALID_STATE")
    r["status"] = "ACTIVE"
    bump(r)
    return success(r)


def settle(rid):
    parse_headers()
    require_role("PlatformAdmin")
    r = _load(rid)
    if r["status"] == "CLOSED":
        raise fail("ERR_INVALID_STATE")
    r["pending_settlement_cents"] = 0
    # Any PENDING restaurant fines clear as part of this settlement cycle: the underlying
    # settlement event has cleared the balance (PRD §3.9 definition of SETTLED).
    for f in store.fines.values():
        if (f["subject_type"] == "RESTAURANT" and f["subject_id"] == r["id"]
                and f["settlement_status"] == "PENDING"):
            f["settlement_status"] = "SETTLED"
    bump(r)
    return success(r)
