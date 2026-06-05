from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from flask import request
import errors
from errors import err


def parse_dt(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_VALIDATION, f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, str):
        raise err(errors.ERR_VALIDATION, f"Field {key} must be an ISO8601 datetime string")
    return parse_iso(v, key)


def parse_iso(v, key="datetime"):
    s = v
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(errors.ERR_VALIDATION, f"Field {key} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def get_body():
    if request.content_length in (None, 0):
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err(errors.ERR_VALIDATION, "Body is not valid JSON")
    if data is None:
        # An empty/no body -> treat as {}
        raw = request.get_data(as_text=True)
        if raw is None or raw.strip() == "":
            return {}
        raise err(errors.ERR_VALIDATION, "Body is not valid JSON")
    if not isinstance(data, dict):
        raise err(errors.ERR_VALIDATION, "Body must be a JSON object")
    return data


def round_half_up(numer, denom):
    """Round (numer/denom) half-up to nearest integer. numer/denom are ints."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def require_int(body, key, required=True, default=None, min_value=None, gt=None):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_VALIDATION, f"Missing required field: {key}")
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_VALIDATION, f"Field {key} must be an integer")
    if min_value is not None and v < min_value:
        raise err(errors.ERR_VALIDATION, f"Field {key} must be >= {min_value}")
    if gt is not None and v <= gt:
        raise err(errors.ERR_VALIDATION, f"Field {key} must be > {gt}")
    return v


def require_str(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_VALIDATION, f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, str):
        raise err(errors.ERR_VALIDATION, f"Field {key} must be a string")
    return v


def require_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_VALIDATION, f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise err(errors.ERR_VALIDATION, f"Field {key} must be a boolean")
    return v


def require_enum(body, key, choices, required=True, default=None):
    v = require_str(body, key, required=required, default=default)
    if v is None:
        return None
    if v not in choices:
        raise err(errors.ERR_VALIDATION, f"Field {key} must be one of {sorted(choices)}")
    return v


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_VALIDATION, "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: list already sorted. Returns (page_items, meta_dict)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda o: o["_seq"])
