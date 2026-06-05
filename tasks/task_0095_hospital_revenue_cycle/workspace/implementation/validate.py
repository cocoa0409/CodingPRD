"""Body-validation helpers (PRD 2.7). These raise ERR_INVALID_REQUEST for
missing/wrong-typed/out-of-set fields and ERR_VALIDATION_OUT_OF_RANGE for
numeric fields outside their permitted range."""
import errors


def get_body():
    """Parse the JSON body; a non-object/absent body is treated as {}."""
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_str(body, field, max_len=None, allow_empty=False):
    if field not in body:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    v = body[field]
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field '{field}' must be a string.")
    if not allow_empty and v.strip() == "":
        raise errors.invalid_request(f"Field '{field}' must be non-empty.")
    if max_len is not None and len(v) > max_len:
        raise errors.invalid_request(f"Field '{field}' exceeds maximum length {max_len}.")
    return v


def require_enum(body, field, allowed):
    if field not in body:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def _is_int(v):
    # bool is a subclass of int; reject booleans where an integer is expected.
    return isinstance(v, int) and not isinstance(v, bool)


def require_int(body, field):
    if field not in body:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    v = body[field]
    if not _is_int(v):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    return v


def require_number(body, field):
    if field not in body:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number.")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field '{field}' must be a boolean.")
    return v


def range_check(value, field, lo=None, hi=None):
    """Range gate -> ERR_VALIDATION_OUT_OF_RANGE (422)."""
    if lo is not None and value < lo:
        raise errors.validation_out_of_range(f"Field '{field}' is below the minimum of {lo}.")
    if hi is not None and value > hi:
        raise errors.validation_out_of_range(f"Field '{field}' is above the maximum of {hi}.")
    return value
