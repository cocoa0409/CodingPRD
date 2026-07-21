"""Input shape/type validation helpers (SCAFFOLD validations priority 3, ERR_VALIDATION)."""
from flask import request
from errors import err


def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_str(d, name, required=True, default=None):
    if name not in d or d.get(name) is None:
        if required:
            raise err("ERR_VALIDATION", f"'{name}' is required.")
        return default
    v = d.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", f"'{name}' must be a non-empty string.")
    return v


def require_int(d, name, required=True, default=None, positive=False, non_negative=False, min_v=None, max_v=None):
    if name not in d or d.get(name) is None:
        if required:
            raise err("ERR_VALIDATION", f"'{name}' is required.")
        return default
    v = d.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"'{name}' must be an integer.")
    if positive and v <= 0:
        raise err("ERR_VALIDATION", f"'{name}' must be a positive integer.")
    if non_negative and v < 0:
        raise err("ERR_VALIDATION", f"'{name}' must be >= 0.")
    if min_v is not None and v < min_v:
        raise err("ERR_VALIDATION", f"'{name}' must be >= {min_v}.")
    if max_v is not None and v > max_v:
        raise err("ERR_VALIDATION", f"'{name}' must be <= {max_v}.")
    return v


def require_number(d, name, required=True, default=None, min_v=None, max_v=None, exclusive_min=False):
    if name not in d or d.get(name) is None:
        if required:
            raise err("ERR_VALIDATION", f"'{name}' is required.")
        return default
    v = d.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"'{name}' must be a number.")
    if min_v is not None:
        if exclusive_min and v <= min_v:
            raise err("ERR_VALIDATION", f"'{name}' must be > {min_v}.")
        if not exclusive_min and v < min_v:
            raise err("ERR_VALIDATION", f"'{name}' must be >= {min_v}.")
    if max_v is not None and v > max_v:
        raise err("ERR_VALIDATION", f"'{name}' must be <= {max_v}.")
    return v


def require_bool(d, name, required=True, default=None):
    if name not in d or d.get(name) is None:
        if required:
            raise err("ERR_VALIDATION", f"'{name}' is required.")
        return default
    v = d.get(name)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"'{name}' must be a boolean.")
    return v


def require_enum(d, name, allowed, required=True, default=None):
    if name not in d or d.get(name) is None:
        if required:
            raise err("ERR_VALIDATION", f"'{name}' is required.")
        return default
    v = d.get(name)
    if v not in allowed:
        raise err("ERR_VALIDATION", f"'{name}' must be one of {sorted(allowed)}.")
    return v


def require_list(d, name, required=False, default=None):
    if name not in d or d.get(name) is None:
        if required:
            raise err("ERR_VALIDATION", f"'{name}' is required.")
        return default if default is not None else []
    v = d.get(name)
    if not isinstance(v, list):
        raise err("ERR_VALIDATION", f"'{name}' must be an array.")
    return v


def require_line_items(items):
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise err("ERR_VALIDATION", "Each line item must be an object.")
        desc = item.get("description")
        amt = item.get("amount_cents")
        if not isinstance(desc, str) or desc == "":
            raise err("ERR_VALIDATION", "line_items[].description must be a non-empty string.")
        if isinstance(amt, bool) or not isinstance(amt, int):
            raise err("ERR_VALIDATION", "line_items[].amount_cents must be an integer.")
        result.append({"description": desc, "amount_cents": amt})
    return result


def require_datetime(d, name, required=True):
    from db import parse_ts
    v = d.get(name)
    if v is None:
        if required:
            raise err("ERR_VALIDATION", f"'{name}' is required.")
        return None
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"'{name}' must be an ISO 8601 datetime string.")
    try:
        return parse_ts(v)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", f"'{name}' must be a valid ISO 8601 datetime string.")
