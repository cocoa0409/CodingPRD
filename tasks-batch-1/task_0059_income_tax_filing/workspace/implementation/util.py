from datetime import datetime, timezone
from flask import request
import errors
from errors import err


def parse_iso(v, key="datetime"):
    if not isinstance(v, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be an ISO8601 datetime string")
    s = v
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def require_dt(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    return parse_iso(body[key], key)


def get_body():
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        raw = request.get_data(as_text=True)
        if raw is None or raw.strip() == "":
            return {}
        raise err(errors.ERR_INVALID_REQUEST, "Body is not valid JSON")
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require_int(body, key, required=True, default=None, min_value=None, gt=None,
                max_value=None):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be an integer")
    if min_value is not None and v < min_value:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be >= {min_value}")
    if gt is not None and v <= gt:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be > {gt}")
    if max_value is not None and v > max_value:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be <= {max_value}")
    return v


def require_str(body, key, required=True, default=None, non_empty=False):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be a string")
    if non_empty and v == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be non-empty")
    return v


def require_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be a boolean")
    return v


def require_enum(body, key, choices, required=True, default=None):
    v = require_str(body, key, required=required, default=default)
    if v is None:
        return None
    if v not in choices:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {key} must be one of {sorted(choices)}")
    return v


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
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
