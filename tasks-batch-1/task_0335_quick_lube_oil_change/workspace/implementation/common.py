"""Common helpers: id minting, body validation, pagination, rounding, stamping."""
import uuid
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request

import clock
from errors import ApiError, ERR_VALIDATION


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return clock.iso(clock.now())


# --- body parsing ---------------------------------------------------------

def get_json_or_400() -> dict:
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_VALIDATION, 400, "invalid JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "body must be a JSON object")
    return data


def require_str(d: dict, key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_VALIDATION, 400, f"missing or invalid {key}")
    return v


def optional_str(d: dict, key: str, default=None):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"{key} must be a string")
    return v


def require_int(d: dict, key: str, *, minimum=None, maximum=None) -> int:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, f"missing or invalid {key}")
    if minimum is not None and v < minimum:
        raise ApiError(ERR_VALIDATION, 400, f"{key} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError(ERR_VALIDATION, 400, f"{key} above maximum {maximum}")
    return v


def optional_int(d: dict, key: str, default=None, *, minimum=None, maximum=None):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, f"{key} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError(ERR_VALIDATION, 400, f"{key} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError(ERR_VALIDATION, 400, f"{key} above maximum {maximum}")
    return v


def require_number(d: dict, key: str, *, minimum=None, maximum=None,
                   min_inclusive=True, max_inclusive=True) -> float:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_VALIDATION, 400, f"missing or invalid {key}")
    fv = float(v)
    if minimum is not None:
        if min_inclusive and fv < minimum:
            raise ApiError(ERR_VALIDATION, 400, f"{key} below minimum {minimum}")
        if not min_inclusive and fv <= minimum:
            raise ApiError(ERR_VALIDATION, 400, f"{key} must be > {minimum}")
    if maximum is not None:
        if max_inclusive and fv > maximum:
            raise ApiError(ERR_VALIDATION, 400, f"{key} above maximum {maximum}")
        if not max_inclusive and fv >= maximum:
            raise ApiError(ERR_VALIDATION, 400, f"{key} must be < {maximum}")
    return fv


def optional_number(d: dict, key: str, default=None, *, minimum=None, maximum=None,
                    min_inclusive=True, max_inclusive=True):
    if key not in d or d[key] is None:
        return default
    return require_number(d, key, minimum=minimum, maximum=maximum,
                          min_inclusive=min_inclusive, max_inclusive=max_inclusive)


def require_bool(d: dict, key: str, default=None):
    if key not in d or d[key] is None:
        if default is None:
            raise ApiError(ERR_VALIDATION, 400, f"missing {key}")
        return default
    v = d[key]
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, f"{key} must be a boolean")
    return v


def require_enum(d: dict, key: str, allowed) -> str:
    v = require_str(d, key)
    if v not in allowed:
        raise ApiError(ERR_VALIDATION, 400, f"{key} not one of {sorted(allowed)}")
    return v


def require_iso_datetime(d: dict, key: str):
    s = require_str(d, key)
    try:
        return clock.parse_iso(s)
    except Exception:
        raise ApiError(ERR_VALIDATION, 400, f"{key} is not a valid ISO 8601 timestamp")


# --- pagination (PRD §2.3) ------------------------------------------------

def parse_pagination():
    """limit defaults 10, range [1,100]; offset defaults 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit out of range [1, 100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def paginate(rows: list, limit: int, offset: int):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


def sort_by_created(rows: list) -> list:
    """List endpoints default to created_at ascending (PRD §2.3)."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))


# --- rounding (PRD §2.7) --------------------------------------------------

def round_half_up(value) -> int:
    """round_half_up(x) = floor(x + 0.5); via Decimal ROUND_HALF_UP on cents."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(value) -> int:
    """Floor to integer (used for the discount cap, no rounding up)."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_FLOOR))


# --- common-field stamping (PRD §2.4) -------------------------------------

def stamp_create(entity: dict, *, with_common: bool = True) -> dict:
    """Stamp id + created_at (+ updated_at + version when with_common)."""
    ts = now_iso()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    if with_common:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity: dict) -> None:
    """A mutation: bump version by one and refresh updated_at (PRD §2.4)."""
    if "version" in entity:
        entity["version"] = entity.get("version", 0) + 1
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
