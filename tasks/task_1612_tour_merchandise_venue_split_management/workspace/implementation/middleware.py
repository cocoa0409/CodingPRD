"""Auth middleware and request-validation helpers (PRD §2.1, §2.3, §2.4)."""

import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from clock import now_iso_ms
from db import DB
from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_VALIDATION,
    err,
)

ROLES = {"TourManager", "Seller", "Accountant", "VenueRep"}


def require_auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role).

    Seller role must be backed by an existing Seller id (PRD §2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID or X-User-Role header missing or role unrecognized",
        )
    if role == "Seller" and user_id not in DB.sellers:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Seller role requires X-User-ID of an existing Seller",
        )
    return user_id, role


def require_role(*roles):
    user_id, role = require_auth()
    if role not in roles:
        raise err(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this endpoint")
    return user_id, role


# ---------- generic request-body validation ----------

def get_json_body():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_VALIDATION, 400, f"Missing required field: {f}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_int(body, name, gt=None, ge=None, required=False):
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_VALIDATION, 400, f"Missing required field: {name}")
        return None
    if not is_int(v):
        raise err(ERR_VALIDATION, 400, f"Field {name} must be an integer")
    if gt is not None and not (v > gt):
        raise err(ERR_VALIDATION, 400, f"Field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err(ERR_VALIDATION, 400, f"Field {name} must be >= {ge}")
    return v


def require_bps(body, name, required=False):
    v = require_int(body, name, ge=0, required=required)
    if v is not None and v > 10000:
        raise err(ERR_VALIDATION, 400, f"Field {name} must be between 0 and 10000")
    return v


def require_enum(body, name, choices, required=False):
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_VALIDATION, 400, f"Missing required field: {name}")
        return None
    if v not in choices:
        raise err(ERR_VALIDATION, 400, f"Field {name} must be one of {sorted(choices)}")
    return v


def require_bool(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err(ERR_VALIDATION, 400, f"Field {name} must be a boolean")
    return v


def require_string(body, name, required=False):
    v = body.get(name)
    if v is None:
        if required:
            raise err(ERR_VALIDATION, 400, f"Missing required field: {name}")
        return None
    if not isinstance(v, str):
        raise err(ERR_VALIDATION, 400, f"Field {name} must be a string")
    return v


# ---------- entity helpers ----------

def new_id():
    return str(uuid.uuid4())


def base_fields():
    ts = now_iso_ms()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    """Bump updated_at and version for a mutation."""
    entity["updated_at"] = now_iso_ms()
    entity["version"] += 1


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
            raise err(ERR_VALIDATION, 400, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_VALIDATION, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def round_half_up_cents(numerator, denominator=10000):
    """round_half_up(numerator / denominator) to integer cents using Decimal."""
    d = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(d)


SIZES_SIZED = ("S", "M", "L", "XL")
SIZE_ORDER = {"S": 0, "M": 1, "L": 2, "XL": 3, "OS": 4}
