"""Request body schema validation helpers (priority 5)."""
import errors


def body_json():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"{field} must be a non-empty string")
    return v


def req_int(data, field, minimum=None, maximum=None, gt=None, lt=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"{field} must be <= {maximum}")
    if gt is not None and not v > gt:
        raise errors.invalid_request(f"{field} must be > {gt}")
    if lt is not None and not v < lt:
        raise errors.invalid_request(f"{field} must be < {lt}")
    return v


def req_number(data, field, gt=None, lt=None, minimum=None, maximum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"{field} must be a number")
    if gt is not None and not v > gt:
        raise errors.invalid_request(f"{field} must be > {gt}")
    if lt is not None and not v < lt:
        raise errors.invalid_request(f"{field} must be < {lt}")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"{field} must be <= {maximum}")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise errors.invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def opt_int(data, field, default=None, **kw):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, **kw)


def opt_number(data, field, default=None, **kw):
    if field not in data or data[field] is None:
        return default
    return req_number(data, field, **kw)


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_str(data, field)
