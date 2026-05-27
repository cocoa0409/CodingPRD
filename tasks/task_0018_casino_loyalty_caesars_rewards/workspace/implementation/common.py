"""Common helpers: id minting, payload validation, pagination, rounding."""
import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return clock.iso(clock.now())


def get_json_or_400() -> dict:
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "body must be a JSON object")
    return data


def require_str(d: dict, key: str, *, max_len=None) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"missing or invalid {key}")
    if max_len is not None and len(v) > max_len:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} exceeds max length {max_len}")
    return v


def optional_str(d: dict, key: str, default=None):
    v = d.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} must be string")
    return v


def require_int(d: dict, key: str, *, minimum=None, maximum=None) -> int:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"missing or invalid {key}")
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} above maximum {maximum}")
    return v


def optional_int(d: dict, key: str, default=None, *, minimum=None, maximum=None):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} must be integer")
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} above maximum {maximum}")
    return v


def require_enum(d: dict, key: str, allowed) -> str:
    v = require_str(d, key)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} not in {sorted(allowed)}")
    return v


def require_iso_datetime(d: dict, key: str):
    s = require_str(d, key)
    try:
        return clock.parse_iso(s)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{key} is not a valid ISO 8601 timestamp")


# --- pagination ---------------------------------------------------------

def parse_pagination():
    """Parse limit/offset query params per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit out of range [1, 100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset below 0")
    return limit, offset


def paginate(rows: list, limit: int, offset: int):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


# --- rounding -----------------------------------------------------------

def round_half_up_int(value) -> int:
    """Round to integer using ROUND_HALF_UP via Decimal."""
    d = Decimal(str(value))
    q = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_half_up_dp(value, places: int):
    """Round to `places` decimal places HALF_UP, returns float."""
    d = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    q = d.quantize(quant, rounding=ROUND_HALF_UP)
    return float(q)


# --- existence ----------------------------------------------------------

def get_or_404(store: dict, key, kind: str) -> dict:
    if not isinstance(key, str) or key not in store:
        raise ApiError(ERR_NOT_FOUND, 404, f"{kind} not found")
    return store[key]


def fk_or_404(store: dict, key, kind: str) -> dict:
    if not isinstance(key, str) or key not in store:
        raise ApiError(ERR_NOT_FOUND, 404, f"{kind} not found")
    return store[key]


# --- common-field stamping ---------------------------------------------

def stamp_create(entity: dict, *, with_common: bool = True) -> None:
    """For entities with common_fields=true: id, created_at, updated_at, version."""
    ts = now_iso()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    if with_common:
        entity["updated_at"] = ts
        entity["version"] = 1


def stamp_audit_create(entity: dict) -> None:
    """For SelfExclusion / VelocityAlert: id + created_at only."""
    entity.setdefault("id", new_id())
    entity["created_at"] = now_iso()


def stamp_update(entity: dict) -> None:
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
