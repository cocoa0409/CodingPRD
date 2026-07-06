"""Body/enum validators for write endpoints (priority 35 = ERR_INVALID_REQUEST).

These run after existence checks but before state / OCC / ownership / temporal / etc.
They must therefore focus on well-formedness and enum membership only.
"""
from errors import bad_request
from util import parse_iso

SIZE_ENUM = {"PETITE", "ORIGINAL", "DELUXE", "GRAND"}
STYLE_ENUM = {"ROUND", "GARDEN", "EUROPEAN"}
CADENCE_ENUM = {"WEEKLY", "BIWEEKLY", "MONTHLY"}
GRADE_ENUM = {"A", "B", "C"}
PAYMENT_OUTCOME_ENUM = {"SUCCEEDED", "FAILED"}
REFUND_DESTINATION_ENUM = {"WALLET"}


def require_dict(body):
    if not isinstance(body, dict):
        raise bad_request("body must be a JSON object")


def require(body, field):
    if field not in body or body[field] is None:
        raise bad_request(f"missing required field '{field}'")
    return body[field]


def require_str(body, field, allow_empty=False):
    v = require(body, field)
    if not isinstance(v, str):
        raise bad_request(f"'{field}' must be a string")
    if not allow_empty and not v.strip():
        raise bad_request(f"'{field}' must not be empty")
    return v


def optional_str(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise bad_request(f"'{field}' must be a string")
    return v


def require_int(body, field, min_value=None, max_value=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"'{field}' must be an integer")
    if min_value is not None and v < min_value:
        raise bad_request(f"'{field}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise bad_request(f"'{field}' must be <= {max_value}")
    return v


def optional_int(body, field, default=None, min_value=None, max_value=None):
    v = body.get(field, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"'{field}' must be an integer")
    if min_value is not None and v < min_value:
        raise bad_request(f"'{field}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise bad_request(f"'{field}' must be <= {max_value}")
    return v


def require_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise bad_request(f"'{field}' must be a boolean")
    return v


def optional_bool(body, field, default=False):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise bad_request(f"'{field}' must be a boolean")
    return v


def require_enum(body, field, enum):
    v = require_str(body, field)
    if v not in enum:
        raise bad_request(f"'{field}' must be one of {sorted(enum)}")
    return v


def optional_enum(body, field, enum, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if v not in enum:
        raise bad_request(f"'{field}' must be one of {sorted(enum)}")
    return v


def require_datetime(body, field):
    s = require_str(body, field)
    try:
        return parse_iso(s), s
    except ValueError:
        raise bad_request(f"'{field}' must be ISO8601 UTC")


def optional_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default, default
    s = body[field]
    if not isinstance(s, str):
        raise bad_request(f"'{field}' must be a string")
    try:
        return parse_iso(s), s
    except ValueError:
        raise bad_request(f"'{field}' must be ISO8601 UTC")


def optional_number(body, field, default=None, min_value=None, max_value=None):
    v = body.get(field, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request(f"'{field}' must be a number")
    if min_value is not None and v < min_value:
        raise bad_request(f"'{field}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise bad_request(f"'{field}' must be <= {max_value}")
    return v
