"""Auth middleware, request-body validation helpers, pagination, numerics."""

import uuid
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import request

from clock import now_iso, parse_iso
from db import DB
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    err,
)

# The nine recognized role names (PRD §2.1).
ROLES = {
    "Trader",
    "RiskManager",
    "LogisticsCoordinator",
    "WarehouseClerk",
    "HeadRoaster",
    "RoastOperator",
    "QAGrader",
    "FulfillmentPlanner",
    "PlatformAdmin",
}

# System-managed field names present on most resources; a client submitting
# them has them ignored (they are never "unknown fields").
COMMON_SYS = {"id", "created_at", "updated_at", "version"}


# ---------- auth ----------

def require_auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(ERR_UNAUTHENTICATED, "X-User-ID header missing or malformed")
    if not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "X-User-Role header missing or role unrecognized")
    return user_id, role


def require_role(*roles):
    user_id, role = require_auth()
    if role not in roles:
        raise err(ERR_FORBIDDEN, "Role not permitted to invoke this endpoint")
    return user_id, role


# ---------- request body ----------

def get_json_body():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def check_unknown_fields(body, allowed):
    for k in body.keys():
        if k not in allowed:
            raise err(ERR_INVALID_REQUEST, f"Unknown field: {k}")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def v_string(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def v_int(body, name, required=True, gt=None, ge=None):
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return None
    if not is_number(v):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if isinstance(v, float):
        if not v.is_integer():
            raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
        v = int(v)
    if gt is not None and not (v > gt):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {ge}")
    return v


def v_num(body, name, required=True, gt=None, ge=None, le=None):
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return None
    if not is_number(v):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if gt is not None and not (v > gt):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {ge}")
    if le is not None and not (v <= le):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be <= {le}")
    return v


def v_enum(body, name, choices, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return None
    if v not in choices:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(choices)}")
    return v


def v_iso(body, name, required=True):
    """Validate an ISO-8601 datetime string field; returns the raw string."""
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 timestamp string")
    try:
        parse_iso(v)
    except Exception:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a valid ISO 8601 timestamp")
    return v


def occ_value(body, name):
    """Extract an OCC expected-version field for comparison.

    Returns (present, int_value). present=False means absent/None (the
    structural required-field check reports it later); int_value=None means
    present but not integer-comparable (an OCC mismatch).
    """
    if name not in body or body[name] is None:
        return False, None
    v = body[name]
    if isinstance(v, bool):
        return True, None
    if isinstance(v, int):
        return True, v
    if isinstance(v, float) and v.is_integer():
        return True, int(v)
    return True, None


# ---------- entity helpers ----------

def new_id():
    return str(uuid.uuid4())


def base_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }


def touch(entity):
    """Bump updated_at and version for a mutation (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def pub(entity):
    """Public view: strip internal underscore-prefixed bookkeeping keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def paginate(items):
    """Apply limit/offset per PRD §2.3 (defaults 10/0, min 1, max 100)."""
    q = request.args
    limit_raw = q.get("limit")
    offset_raw = q.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_created(items):
    """created_at ascending; the logical clock freezes timestamps, so the
    monotonic creation sequence breaks ties in insertion order."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------- decimal helpers (PRD §2.5 precision contracts) ----------

def D(x):
    return Decimal(str(x))


def q2(x):
    """Dollar amounts: 2 decimal places, round half-up."""
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def q5(x):
    """Per-pound price levels / cost bases / yield ratios: 5 dp, half-up."""
    return float(D(x).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))


def q1(x):
    """Cup score on the SCA scale: 1 decimal, half-up."""
    return float(D(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def floor_int(x):
    return int(D(x).to_integral_value(rounding=ROUND_FLOOR))
