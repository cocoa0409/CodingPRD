"""Request-body well-formedness helpers (ERR_INVALID_REQUEST, priority 4)."""
import errors


def body(req):
    data = req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require(data, *names):
    for name in names:
        if name not in data or data[name] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def require_str(data, name):
    require(data, name)
    v = data[name]
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def enum(data, name, allowed, required=True):
    if name not in data or data[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return None
    v = data[name]
    if v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid value for %s" % name)
    return v


def non_negative_int(data, name, required=True, default=0):
    if name not in data or data[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if v < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be non-negative" % name)
    return v


def positive_int(data, name, required=True, default=1):
    v = non_negative_int(data, name, required=required, default=default)
    if v < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be >= 1" % name)
    return v


def optional_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v
