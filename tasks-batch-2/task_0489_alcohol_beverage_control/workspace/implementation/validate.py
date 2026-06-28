"""Body well-formedness checks (ERR_INVALID_REQUEST, priority 22). These run
AFTER auth/existence/state/segregation per the PRD validation ordering, except
where a field is required to resolve a referenced resource."""
import re

import errors


def require(data, field):
    if field not in data or data[field] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing field: %s" % field)
    return data[field]


def require_str(data, field, allow_empty=False):
    val = require(data, field)
    if not isinstance(val, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a string" % field)
    if not allow_empty and val.strip() == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be non-empty" % field)
    return val


def require_int(data, field, minimum=None):
    val = require(data, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s below minimum" % field)
    return val


def opt_int(data, field, default, minimum=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s below minimum" % field)
    return val


def require_bool(data, field):
    val = require(data, field)
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return val


def opt_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return val


def require_enum(data, field, members):
    val = require(data, field)
    if val not in members:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s not a valid value" % field)
    return val


def match_pattern(value, pattern, field):
    if not re.match(pattern, value):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s has invalid format" % field)
    return value
