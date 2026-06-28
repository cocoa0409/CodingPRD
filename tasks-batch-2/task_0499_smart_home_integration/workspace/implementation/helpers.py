"""Shared request helpers: body parsing, validation primitives, pagination,
serialization, and lookups."""
from datetime import datetime, timezone

from flask import request

import db
from errors import err

# Enumerations (scaffold §1.1)
REGION_CODES = {"NORTH", "SOUTH", "EAST", "WEST"}
BILLING_TIERS = {"RESIDENTIAL", "COMMERCIAL"}
DEVICE_CATEGORIES = {"CONTROLLER", "AUDIO", "VIDEO", "NETWORK", "LIGHTING", "ACCESSORY"}
VISIT_KINDS = {"INSTALL", "COMMISSION", "SERVICE"}
CERT_LEVELS = {"APPRENTICE", "JOURNEYMAN", "MASTER"}
CONTRACT_PLANS = {"BASIC", "PLUS", "PREMIER"}
FAULT_CODES = {"HARDWARE", "FIRMWARE", "NETWORK", "POWER"}
RMA_RESOLUTIONS = {"RETURN_REPAIR", "ADVANCE_REPLACE"}


# ---------------------------------------------------------------------------
# Body parsing / validation primitives (priority 5: ERR_INVALID_REQUEST, 422)
# ---------------------------------------------------------------------------
def get_body():
    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
    else:
        body = {}
    if body is None:
        raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def require_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def require_number(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def optional_number(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def parse_iso(value, field="datetime"):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0 min 0
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        elif limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v


def sort_by_creation(items):
    return sorted(items, key=lambda e: e.get("_seq", 0))


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Existence lookups (priority 3: ERR_NOT_FOUND, 404), left-to-right
# ---------------------------------------------------------------------------
def get_or_404(store, ident):
    e = store.get(ident)
    if e is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return e


# ---------------------------------------------------------------------------
# Serialization: strip internal fields (those prefixed with "_")
# ---------------------------------------------------------------------------
def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}
