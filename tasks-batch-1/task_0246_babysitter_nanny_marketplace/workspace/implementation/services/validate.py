"""Body field validation helpers (ERR_VALIDATION, priority 17).

These are the final catch-all checks: required field present, well-typed,
enum in domain, number in range. Interval ordering and business rules are
enforced separately (earlier priority) in the route handlers.
"""

import errors
from db import parse_dt
from errors import err


def require(body, field):
    if field not in body or body[field] is None:
        raise err(errors.ERR_VALIDATION, f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val.strip() == "":
        raise err(errors.ERR_VALIDATION, f"Field {field} must be a non-empty string")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(errors.ERR_VALIDATION, f"Field {field} must be a string")
    return val


def req_int(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_VALIDATION, f"Field {field} must be an integer")
    _range_check(field, val, minimum, maximum)
    return val


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_VALIDATION, f"Field {field} must be an integer")
    _range_check(field, val, minimum, maximum)
    return val


def _range_check(field, val, minimum, maximum):
    if minimum is not None and val < minimum:
        raise err(errors.ERR_VALIDATION, f"Field {field} below minimum {minimum}")
    if maximum is not None and val > maximum:
        raise err(errors.ERR_VALIDATION, f"Field {field} above maximum {maximum}")


def req_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise err(errors.ERR_VALIDATION, f"Field {field} must be a boolean")
    return val


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_VALIDATION, f"Field {field} must be a boolean")
    return val


def req_enum(body, field, domain):
    val = require(body, field)
    if not isinstance(val, str) or val not in domain:
        raise err(errors.ERR_VALIDATION,
                  f"Field {field} must be one of {sorted(domain)}")
    return val


def opt_enum(body, field, domain, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in domain:
        raise err(errors.ERR_VALIDATION,
                  f"Field {field} must be one of {sorted(domain)}")
    return val


def req_datetime(body, field):
    val = require(body, field)
    dt = parse_dt(val)
    if dt is None:
        raise err(errors.ERR_VALIDATION, f"Field {field} must be an ISO 8601 datetime")
    return dt


def req_str_list(body, field):
    val = require(body, field)
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise err(errors.ERR_VALIDATION, f"Field {field} must be a list of strings")
    return val
