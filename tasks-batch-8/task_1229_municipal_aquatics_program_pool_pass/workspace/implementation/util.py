"""Request field validation helpers (priority-22 shape checks)."""
from errors import err_invalid_request


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request(f"Field '{name}' is required and must be a non-empty string")
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid_request(f"Field '{name}' must be a string")
    return v


def req_int(body, name, minimum=None):
    v = body.get(name)
    if not is_int(v):
        raise err_invalid_request(f"Field '{name}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"Field '{name}' must be >= {minimum}")
    return v


def req_num(body, name):
    v = body.get(name)
    if not is_num(v):
        raise err_invalid_request(f"Field '{name}' is required and must be a number")
    return v


def req_enum(body, name, members):
    v = body.get(name)
    if not isinstance(v, str) or v not in members:
        raise err_invalid_request(f"Field '{name}' must be one of {sorted(members)}")
    return v
