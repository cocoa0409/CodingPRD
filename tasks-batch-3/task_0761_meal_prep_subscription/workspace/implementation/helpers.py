"""Error type, response envelope, auth, validation and serialization helpers."""
from flask import request, jsonify

import store
from store import db, now_clock, format_ms, new_request_id


# --------------------------------------------------------------------------
# Error type
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_ms(now_clock()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def err_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authenticate(required=True):
    """Return (user_id, role). On authenticated endpoints validate headers."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not required:
        return uid, role
    if not uid or not role or role not in store.KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unknown X-User-ID / X-User-Role")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role %s is not permitted for this operation" % role)


def deny_ownership():
    raise ApiError("ERR_UNAUTHORIZED", 403, "Not the owner of the targeted resource")


# --------------------------------------------------------------------------
# Body / value validation
# --------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object")
    return data


def require_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: %s" % field)
    return body[field]


def as_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be >= %s" % (field, minimum))
    return value


def require_str(body, field):
    val = require_present(body, field)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be a non-empty string" % field)
    return val


def as_str_array(value, field):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be an array of strings" % field)
    return value


# --------------------------------------------------------------------------
# Pagination (priority 12)
# --------------------------------------------------------------------------
def read_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", 400, "limit must be within [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset, serializer):
    """Sort by (created_at, seq), window, and build list envelope pieces."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    data = [serializer(e) for e in window]
    return data, pagination


# --------------------------------------------------------------------------
# Wallet / par derived fields
# --------------------------------------------------------------------------
def wallet_balance(customer_id):
    return sum(e["amount_cents"] for e in db.ledger.values()
               if e["customer_id"] == customer_id)


def recompute_run_par(run):
    reserved = sum(bi["quantity"] for bi in db.box_items.values()
                   if bi["status"] == "SELECTED" and bi.get("reserved_run_id") == run["id"])
    run["par_reserved"] = reserved
    run["par_remaining"] = run["par_total"] - reserved


# --------------------------------------------------------------------------
# Serializers (strip internal keys, add computed fields)
# --------------------------------------------------------------------------
def _public(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def ser_zone(e):
    return _public(e)


def ser_plan(e):
    return _public(e)


def ser_meal(e):
    return _public(e)


def ser_run(e):
    recompute_run_par(e)
    return _public(e)


def ser_customer(e):
    out = _public(e)
    out["wallet_credit_cents"] = wallet_balance(e["id"])
    return out


def ser_subscription(e):
    return _public(e)


def ser_pause(e):
    return _public(e)


def ser_plan_change(e):
    return _public(e)


def ser_box(e):
    return _public(e)


def ser_box_item(e):
    return _public(e)


def ser_referral(e):
    return _public(e)


def ser_ledger(e):
    return _public(e)
