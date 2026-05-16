"""Generic body & pagination validation helpers."""

from flask import request
from core.errors import raise_error
from core.clock import parse_iso


def require_body(req):
    body = req.get_json(silent=True)
    if body is None:
        # Empty body is allowed in some POST /state endpoints; treat as {}.
        if req.content_length in (0, None) and not req.data:
            return {}
        raise_error("ERR_VALIDATION_FAILED", "Request body must be valid JSON object")
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION_FAILED", "Request body must be a JSON object")
    return body


def require_field(body, name, kind=None):
    if name not in body or body[name] is None:
        raise_error("ERR_VALIDATION_FAILED", f"Missing required field '{name}'")
    val = body[name]
    if kind == "int":
        if isinstance(val, bool) or not isinstance(val, int):
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be an integer")
    elif kind == "positive_int":
        if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a positive integer")
    elif kind == "non_neg_int":
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a non-negative integer")
    elif kind == "string":
        if not isinstance(val, str) or not val.strip():
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a non-empty string")
    elif kind == "bool":
        if not isinstance(val, bool):
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a boolean")
    elif kind == "number":
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a number")
    return val


def require_enum(body, name, allowed):
    v = require_field(body, name, kind="string")
    if v not in allowed:
        raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def require_iso_datetime(body, name):
    v = require_field(body, name, kind="string")
    try:
        return parse_iso(v)
    except ValueError:
        raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be ISO 8601")


def parse_pagination(req):
    """Parse limit/offset query args. Defaults limit=10, offset=0; limit in [1,100]."""
    limit_raw = req.args.get("limit")
    offset_raw = req.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (ValueError, TypeError):
        raise_error("ERR_VALIDATION_FAILED", "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise_error("ERR_VALIDATION_FAILED", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error("ERR_VALIDATION_FAILED", "limit must be between 1 and 100")
    if offset < 0:
        raise_error("ERR_VALIDATION_FAILED", "offset must be >= 0")
    return limit, offset


def check_version(body, stored_version):
    """OCC check: if 'version' is supplied in body, compare to stored. Otherwise no-op."""
    if not isinstance(body, dict):
        return
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise_error("ERR_VALIDATION_FAILED", "Field 'version' must be an integer")
        if v != stored_version:
            raise_error("ERR_VERSION_MISMATCH", "Stored version does not match supplied version")


def parse_iso_query(value: str, field_name: str):
    """Parse query-string ISO timestamp; raise ERR_VALIDATION_FAILED on bad format."""
    try:
        return parse_iso(value)
    except ValueError:
        raise_error("ERR_VALIDATION_FAILED", f"Query parameter '{field_name}' must be ISO 8601")
