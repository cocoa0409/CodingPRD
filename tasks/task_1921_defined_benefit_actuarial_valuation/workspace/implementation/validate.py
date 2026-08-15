"""Request-body field helpers. ERR_VALIDATION (400) is the lowest-priority
check per the validation order — these helpers are only invoked after all
higher-priority checks for the endpoint have passed (or leniently, when a
business check needs a field value)."""

from errors import validation

NUM = (int, float)


def body_of(request):
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise validation("Request body must be a JSON object")
    return body


def has_field(body, name):
    return isinstance(body, dict) and name in body and body[name] is not None


def req_field(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise validation(f"Missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise validation(f"{name} must be a string")
    return v


def req_int(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"{name} must be an integer")
    return v


def req_num(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, NUM):
        raise validation(f"{name} must be a number")
    return v


def opt_num(body, name, default=None):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, NUM):
        raise validation(f"{name} must be a number")
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise validation(f"{name} must be one of {sorted(allowed)}")
    return v
