"""Field shape/semantic validation helpers. All failures -> ERR_VALIDATION (422)
unless a more specific error applies per the pipeline."""
from errors import raise_err, ERR_VALIDATION


def req_present(data, field):
    if field not in data or data[field] is None:
        raise_err(ERR_VALIDATION, f"{field} is required")
    return data[field]


def req_string(data, field):
    v = req_present(data, field)
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"{field} must be a string")
    return v


def opt_string(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"{field} must be a string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, field):
    v = req_present(data, field)
    if not _is_int(v):
        raise_err(ERR_VALIDATION, f"{field} must be an integer")
    return v


def opt_int(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not _is_int(v):
        raise_err(ERR_VALIDATION, f"{field} must be an integer")
    return v


def req_number(data, field):
    v = req_present(data, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_VALIDATION, f"{field} must be a number")
    return v


def req_bool(data, field):
    v = req_present(data, field)
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"{field} must be a boolean")
    return v


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"{field} must be a boolean")
    return v


def req_enum(data, field, allowed):
    v = req_present(data, field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_VALIDATION, f"{field} must be one of {sorted(allowed)}")
    return v


def opt_str_list(data, field, default=None):
    if field not in data or data[field] is None:
        return list(default) if default is not None else []
    v = data[field]
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_err(ERR_VALIDATION, f"{field} must be an array of strings")
    return list(v)


def check_range(condition, message):
    if not condition:
        raise_err(ERR_VALIDATION, message)
