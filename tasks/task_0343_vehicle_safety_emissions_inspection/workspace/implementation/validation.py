"""Request-body well-formedness helpers (PRD §2.9, priority 4 -> ERR_INVALID_REQUEST)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import err

VIN_RE = re.compile(r"^[A-Z0-9]{17}$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def get_json_body():
    """Parse the JSON body; tolerate an absent body as an empty object."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        # Non-empty but unparseable, or explicit JSON null.
        if request.data.strip() == b"":
            return {}
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def opt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return val


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return val


def _is_int(val):
    return isinstance(val, int) and not isinstance(val, bool)


def require_int(body, field, min_value=None):
    val = require(body, field)
    if not _is_int(val):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if min_value is not None and val < min_value:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, min_value))
    return val


def opt_int(body, field, default=None, min_value=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_int(val):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if min_value is not None and val < min_value:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, min_value))
    return val


def require_enum(body, field, members):
    val = require(body, field)
    if val not in members:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, sorted(members)))
    return val


def opt_enum(body, field, members, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in members:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, sorted(members)))
    return val


def require_vin(body, field):
    val = require_str(body, field)
    if not VIN_RE.match(val):
        raise err("ERR_INVALID_REQUEST", "Field %s must be exactly 17 uppercase alphanumeric characters." % field)
    return val


def require_state_code(body, field):
    val = require_str(body, field)
    if not STATE_CODE_RE.match(val):
        raise err("ERR_INVALID_REQUEST", "Field %s must be exactly 2 uppercase letters." % field)
    return val


def require_datetime(body, field):
    val = require(body, field)
    return parse_datetime(val, field)


def parse_datetime(val, field="datetime"):
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime string." % field)
    s = val.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_pagination():
    """limit/offset per PRD §2.3. Malformed -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset
