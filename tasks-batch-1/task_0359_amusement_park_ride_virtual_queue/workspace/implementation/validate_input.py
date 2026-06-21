"""Body/field parsing helpers. Malformed input -> ERR_VALIDATION (PRD §2.10)."""
from flask import request

import errors


def get_body():
    """Parse JSON body; absent body is treated as empty object."""
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None:
        if not request.data:
            return {}
        errors.err(errors.ERR_VALIDATION, "Malformed JSON body")
    if not isinstance(data, dict):
        errors.err(errors.ERR_VALIDATION, "Body must be a JSON object")
    return data


def require_str(body, field):
    if field not in body or body[field] is None:
        errors.err(errors.ERR_VALIDATION, f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, str) or val == "":
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be a non-empty string")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be a string")
    return val


def require_int(body, field, min_val=None):
    if field not in body or body[field] is None:
        errors.err(errors.ERR_VALIDATION, f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be an integer")
    if min_val is not None and val < min_val:
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be >= {min_val}")
    return val


def opt_int(body, field, default=None, min_val=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be an integer")
    if min_val is not None and val < min_val:
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be >= {min_val}")
    return val


def require_number(body, field):
    if field not in body or body[field] is None:
        errors.err(errors.ERR_VALIDATION, f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be a number")
    return float(val)


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be a number")
    return float(val)


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be a boolean")
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be one of {sorted(allowed)}")
    return val


def opt_int_param(name, default, min_val=None, max_val=None):
    """Parse a query-string integer (pagination). Out-of-range -> ERR_VALIDATION."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        errors.err(errors.ERR_VALIDATION, f"Query param {name} must be an integer")
    if min_val is not None and val < min_val:
        errors.err(errors.ERR_VALIDATION, f"Query param {name} must be >= {min_val}")
    if max_val is not None and val > max_val:
        errors.err(errors.ERR_VALIDATION, f"Query param {name} must be <= {max_val}")
    return val
