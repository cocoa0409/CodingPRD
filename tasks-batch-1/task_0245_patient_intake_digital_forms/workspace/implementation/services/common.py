"""Shared mutation/validation helpers."""
import db
from errors import err, ERR_INVALID_REQUEST


def touch(record):
    """Record a mutation: refresh updated_at and bump version (PRD §2.4).

    Only resources that carry common fields (have a 'version') are touched.
    EligibilityCheck is append-only and never passes through here.
    """
    if "version" in record:
        record["version"] += 1
        record["updated_at"] = db.now_iso()


def require_field(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return val


def opt_int(body, name, default):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return val


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return val


def opt_string(body, name, default=None):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return val
