"""Body schema and field validation helpers (priority 21: ERR_VALIDATION)."""

from errors import ERR_VALIDATION, raise_error


def require_field(body: dict, name: str):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise_error(ERR_VALIDATION, f"Missing required field: {name}.")
    return body[name]


def require_int(body: dict, name: str, *, min_value=None, max_value=None, allow_none=False):
    if name not in body or body[name] is None:
        if allow_none:
            return None
        raise_error(ERR_VALIDATION, f"Missing required integer field: {name}.")
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_VALIDATION, f"Field {name} must be an integer.")
    if min_value is not None and val < min_value:
        raise_error(ERR_VALIDATION, f"Field {name} must be >= {min_value}.")
    if max_value is not None and val > max_value:
        raise_error(ERR_VALIDATION, f"Field {name} must be <= {max_value}.")
    return val


def require_string(body: dict, name: str, *, allow_empty=False, allow_none=False):
    if name not in body or body[name] is None:
        if allow_none:
            return None
        raise_error(ERR_VALIDATION, f"Missing required string field: {name}.")
    val = body[name]
    if not isinstance(val, str):
        raise_error(ERR_VALIDATION, f"Field {name} must be a string.")
    if not allow_empty and not val.strip():
        raise_error(ERR_VALIDATION, f"Field {name} must be non-empty.")
    return val


def require_enum(body: dict, name: str, allowed, *, allow_none=False):
    if name not in body or body[name] is None:
        if allow_none:
            return None
        raise_error(ERR_VALIDATION, f"Missing required field: {name}.")
    val = body[name]
    if val not in allowed:
        raise_error(
            ERR_VALIDATION,
            f"Field {name} must be one of: {sorted(allowed) if isinstance(allowed, set) else list(allowed)}.",
        )
    return val


def require_list(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_error(ERR_VALIDATION, f"Missing required field: {name}.")
    val = body[name]
    if not isinstance(val, list):
        raise_error(ERR_VALIDATION, f"Field {name} must be an array.")
    return val
