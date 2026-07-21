"""Response envelope, auth/RBAC helpers, pagination, lookup + validation
helpers. Envelope shape is transcribed verbatim from SCAFFOLD §1.0 / PRD §2.2."""
import random
import string
from flask import g, jsonify, request

import store
from errors import ApiError

VALID_ROLES = {"Customer", "Fitter", "StoreManager", "BillingClerk"}


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": store.now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


# --- auth / RBAC -----------------------------------------------------------
def authenticate():
    """before_request hook: every endpoint requires two well-formed headers."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = uid
    g.role = role


def require_role(*roles):
    if g.role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def owner_guard(resource_customer_id):
    """Priority-4 ownership: a Customer may only act on their own resource."""
    if g.role == "Customer" and g.user_id != resource_customer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --- lookups (existence, priority 3) ---------------------------------------
_NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "fitters": "ERR_FITTER_NOT_FOUND",
    "rooms": "ERR_ROOM_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "skus": "ERR_SKU_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "order_lines": "ERR_ORDER_LINE_NOT_FOUND",
    "exchanges": "ERR_EXCHANGE_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "reminders": "ERR_REMINDER_NOT_FOUND",
    "loyalty_events": "ERR_CUSTOMER_NOT_FOUND",  # unused; loyalty events have own err below
}


def lookup(collection_name, rid):
    coll = getattr(store, collection_name)
    rec = coll.get(rid)
    if rec is None:
        raise ApiError(_NOT_FOUND[collection_name])
    return rec


def lookup_loyalty_event(rid):
    rec = store.loyalty_events.get(rid)
    if rec is None:
        # No dedicated error id in the catalogue; loyalty events are read via a
        # customer-scoped surface. Reuse the generic not-found family.
        raise ApiError("ERR_CUSTOMER_NOT_FOUND")
    return rec


# --- body parsing / validation (priority 5) --------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {f}")


def check_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", f"Invalid value for {field}")


def require_int(body, field, minimum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", f"{field} must be >= {minimum}")
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{field} must be a number")
    return v


# --- pagination (PRD §2.3) -------------------------------------------------
def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        # Some harnesses pass GET filters in the JSON body.
        body = request.get_json(silent=True)
        if isinstance(body, dict) and body.get(name) is not None:
            raw = body.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", f"{name} must be an integer")


def filter_arg(name):
    val = request.args.get(name)
    if val is not None:
        return val
    body = request.get_json(silent=True)
    if isinstance(body, dict) and body.get(name) is not None:
        return body.get(name)
    return None


def paginate(records):
    """records: list already sorted. Returns (page, pagination_meta)."""
    limit = _int_arg("limit", 10)
    offset = _int_arg("offset", 0)
    # accepted range: limit 1..100, offset >= 0 (PRD §2.3)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_records(collection_name, predicate=None):
    coll = getattr(store, collection_name)
    items = [r for r in coll.values() if (predicate is None or predicate(r))]
    items.sort(key=lambda r: r["_seq"])
    return items


def list_response(collection_name, serializer, predicate=None):
    records = sorted_records(collection_name, predicate)
    page, meta = paginate(records)
    return success([serializer(r) for r in page], response_type="array",
                   status=200, pagination=meta)


# --- loyalty ledger helper -------------------------------------------------
def append_loyalty_event(customer, points_delta, reason, order_id=None):
    ev = store.new_record({
        "customer_id": customer["id"],
        "points_delta": points_delta,
        "reason": reason,
        "order_id": order_id,
    })
    # LoyaltyEvent is append-only: strip version/updated_at (id + created_at only)
    ev.pop("version", None)
    ev.pop("updated_at", None)
    store.loyalty_events[ev["id"]] = ev
    customer["loyalty_points"] += points_delta
    store.touch(customer)
    return ev
