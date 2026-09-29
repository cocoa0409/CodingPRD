"""Envelope construction, role gate, request parsing and pagination (PRD 2.1-2.3)."""

import json
import random
import string
from decimal import Decimal
from functools import wraps

from flask import g, jsonify, request

import db
from errors import ApiError

ROLES = (
    "PlantAdmin",
    "DesignEngineer",
    "ReliabilityEngineer",
    "CertificationEngineer",
    "RegulatoryAuditor",
    "SupplyPlanner",
    "ProductionPlanner",
    "ProductionTechnician",
    "QualityTechnician",
    "DistributorRep",
    "WarrantyAnalyst",
)

_ALPHANUM = string.ascii_uppercase + string.digits


class Listing(object):
    """Marker for list responses so the envelope can carry pagination meta."""

    def __init__(self, items, total, limit, offset):
        self.items = items
        self.total = total
        self.limit = limit
        self.offset = offset


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": db.db.stamp(),
    }


def _to_jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _to_jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def envelope(payload, status):
    meta = base_meta()
    if isinstance(payload, Listing):
        meta["limit"] = payload.limit
        meta["offset"] = payload.offset
        meta["total_count"] = payload.total
        meta["has_more"] = (payload.offset + len(payload.items)) < payload.total
        body = {
            "meta": meta,
            "response_type": "array",
            "data": _to_jsonable(list(payload.items)),
        }
    else:
        body = {
            "meta": meta,
            "response_type": "object",
            "data": _to_jsonable(payload if payload is not None else {}),
        }
    response = jsonify(body)
    response.status_code = status
    return response


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    response = jsonify(body)
    response.status_code = status
    return response


def actor():
    return g.user_id


def role():
    return g.user_role


def _authorize(allowed):
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHORIZED", "X-User-ID header is required.")
    if not user_role or user_role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "X-User-Role header is missing or unrecognized.")
    if user_role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorized for this operation." % user_role,
        )
    g.user_id = str(user_id)
    g.user_role = user_role


def endpoint(roles, status=200):
    """Wrap a view: serialize access, apply the role gate, build the envelope."""
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                with db.LOCK:
                    _authorize(allowed)
                    result = fn(*args, **kwargs)
                    return envelope(result, status)
            except ApiError as exc:
                return error_response(exc.error_id, exc.message, exc.http_status)

        return wrapper

    return decorator


def body():
    """Parse the JSON request body; Decimals preserved for money/ratings."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is below the permitted minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is above the permitted maximum." % name)
    return value


def page(items):
    """Apply limit / offset to an already-ordered list of serialized rows."""
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    total = len(items)
    window = items[offset : offset + limit]
    return Listing(window, total, limit, offset)


def filter_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_bool(name):
    raw = filter_value(name)
    if raw is None:
        return None
    lowered = str(raw).strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None
