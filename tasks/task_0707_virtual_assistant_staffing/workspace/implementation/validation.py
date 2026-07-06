"""Body validation helpers (PRD §2.7 priority order)."""
from errors import err


def get_json(request):
    """Parse JSON body, defaulting to {} for empty bodies."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def require_fields(body, names):
    """Priority 5: required fields present -> ERR_INVALID_REQUEST."""
    for n in names:
        if body.get(n) is None:
            raise err("ERR_INVALID_REQUEST", f"missing required field: {n}")


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a number")
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")
    return value


def as_str(value, name):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a string")
    return value
