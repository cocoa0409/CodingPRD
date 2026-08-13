"""HTTP plumbing: response envelope, error catalog, auth, body validation,
pagination. All structural names come from SCAFFOLD.yaml / PRD.md:

  success envelope: {"meta": {"api_request_id", "api_request_timestamp"},
                     "response_type": "object"|"array", "data": ...}
  error envelope:   {"meta": {...}, "response_type": "error",
                     "data": {"error_id": ..., "message": ...}}
  pagination:       limit / offset query params; meta carries
                    limit / offset / total_count / has_more
                    (defaults limit=10, offset=0, min 1, max 100)
  auth headers:     X-User-ID + X-User-Role
  roles:            PlatformAdmin | Operator | Client | RetailBroker | CentralAgent
"""

import random
import string

from flask import g, jsonify, request

from store import db
from util import parse_date, wall_now_ts

# ---------------------------------------------------------------------------
# Errors (catalog from SCAFFOLD.yaml table 1.6 / PRD §5)
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_OPERATOR_SUSPENDED": 422,
    "ERR_YACHT_NOT_LISTED": 409,
    "ERR_CLIENT_NOT_QUALIFIED": 422,
    "ERR_RESUME_CLASS_INSUFFICIENT": 422,
    "ERR_BROKER_CONFLICT_OF_INTEREST": 422,
    "ERR_INSURANCE_NOT_VERIFIED": 422,
    "ERR_PERMIT_NOT_GRANTED": 422,
    "ERR_AVAILABILITY_CONFLICT": 409,
    "ERR_TURNAROUND_BUFFER_VIOLATION": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_LEG_OUTSIDE_CHARTER_WINDOW": 422,
    "ERR_PERMIT_WINDOW_INSUFFICIENT": 422,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_CHARTER_DURATION_INVALID": 422,
    "ERR_DUPLICATE_ACTIVE_REQUEST": 409,
    "ERR_NEGOTIATION_ROUND_LIMIT": 409,
    "ERR_GRATUITY_BELOW_MINIMUM": 422,
    "ERR_INSURANCE_COVERAGE_INSUFFICIENT": 422,
    "ERR_INSURANCE_WINDOW_INVALID": 422,
    "ERR_FUNDING_TRANCHE_OUT_OF_ORDER": 422,
    "ERR_FUNDING_AMOUNT_MISMATCH": 422,
    "ERR_ESCROW_INSUFFICIENT": 422,
    "ERR_DEPOSIT_CLAIM_EXCEEDS_HELD": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = (
            http_status if http_status is not None else ERROR_HTTP[error_id]
        )


def api_err(error_id, message):
    return ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=18))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_ts(),
    }
    if extra:
        m.update(extra)
    return m


def respond_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def respond_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination (limit / offset; defaults 10 / 0; limit in [1, 100])
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise api_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if not str(raw_limit).strip().lstrip("+").isdigit():
            raise api_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise api_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if not str(raw_offset).strip().lstrip("+").isdigit():
            raise api_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise api_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def respond_paginated(items):
    """items: full filtered+sorted collection (already serialized)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validation priority 1-2)
# ---------------------------------------------------------------------------

ROLES = {"PlatformAdmin", "Operator", "Client", "RetailBroker", "CentralAgent"}


def authenticate():
    """Priority-1 authentication. Populates g.role / g.user_id / g.actor."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise api_err(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in ROLES:
        raise api_err("ERR_UNAUTHENTICATED", f"Undeclared role: {role}")
    g.user_id = uid
    g.role = role
    g.actor = None
    if role == "PlatformAdmin":
        return  # opaque identity, never compared to entity ids
    if role == "Operator":
        ent = db["operators"].get(uid)
        if ent is None:
            raise api_err(
                "ERR_UNAUTHENTICATED",
                "X-User-ID does not reference an existing Operator",
            )
    elif role == "Client":
        ent = db["clients"].get(uid)
        if ent is None:
            raise api_err(
                "ERR_UNAUTHENTICATED",
                "X-User-ID does not reference an existing Client",
            )
    else:
        broker = db["brokers"].get(uid)
        if broker is None:
            raise api_err(
                "ERR_UNAUTHENTICATED",
                "X-User-ID does not reference an existing Broker",
            )
        needed = ("RETAIL_BROKER", "BOTH") if role == "RetailBroker" else (
            "CENTRAL_AGENT",
            "BOTH",
        )
        if broker["broker_type"] not in needed:
            raise api_err(
                "ERR_UNAUTHENTICATED",
                f"Broker type {broker['broker_type']} does not admit role {role}",
            )
        ent = broker
    g.actor = ent


def require_roles(*roles):
    """Priority-2 role-list membership gate."""
    if g.role not in roles:
        raise api_err(
            "ERR_FORBIDDEN", f"Role {g.role} is not authorized for this endpoint"
        )


def forbidden(msg="Ownership rule violated"):
    raise api_err("ERR_FORBIDDEN", msg)


# ---------------------------------------------------------------------------
# Existence + body validation helpers
# ---------------------------------------------------------------------------

def get_or_404(collection, entity_id, what="Resource"):
    ent = db[collection].get(entity_id)
    if ent is None:
        raise api_err("ERR_NOT_FOUND", f"{what} not found: {entity_id}")
    return ent


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise api_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise api_err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def as_str(value, name):
    if not isinstance(value, str):
        raise api_err("ERR_INVALID_REQUEST", f"{name} must be a string")
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise api_err("ERR_INVALID_REQUEST", f"{name} must be an integer")
    return value


def as_pos_int(value, name):
    value = as_int(value, name)
    if value <= 0:
        raise api_err("ERR_INVALID_REQUEST", f"{name} must be positive")
    return value


def as_nonneg_int(value, name):
    value = as_int(value, name)
    if value < 0:
        raise api_err("ERR_INVALID_REQUEST", f"{name} must be non-negative")
    return value


def as_enum(value, allowed, name):
    if not isinstance(value, str) or value not in allowed:
        raise api_err(
            "ERR_INVALID_REQUEST",
            f"{name} must be one of {sorted(allowed)}",
        )
    return value


def as_date(value, name):
    parsed = parse_date(value)
    if parsed is None:
        raise api_err(
            "ERR_INVALID_REQUEST", f"{name} must be a YYYY-MM-DD calendar date"
        )
    return parsed


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise api_err("ERR_INVALID_REQUEST", f"{name} must be a number")
    return value


def sort_created(records):
    """Default list ordering: created_at ascending (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
