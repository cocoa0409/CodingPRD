"""Request validation helpers. ERR_VALIDATION (HTTP 422) per SCAFFOLD §1.6."""

from datetime import datetime, timezone

from core.errors import raise_error


def require_body(req):
    """Return JSON body as a dict. Empty body returns {} — endpoints that need
    a body must call require_field on a specific key."""
    body = req.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_field(body, name, kind=None):
    if name not in body or body[name] is None:
        raise_error("ERR_VALIDATION", f"Missing required field '{name}'")
    val = body[name]
    if kind == "int":
        if isinstance(val, bool) or not isinstance(val, int):
            raise_error("ERR_VALIDATION", f"Field '{name}' must be an integer")
    elif kind == "positive_int":
        if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise_error("ERR_VALIDATION", f"Field '{name}' must be a positive integer")
    elif kind == "non_neg_int":
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise_error("ERR_VALIDATION", f"Field '{name}' must be a non-negative integer")
    elif kind == "string":
        if not isinstance(val, str) or not val.strip():
            raise_error("ERR_VALIDATION", f"Field '{name}' must be a non-empty string")
    elif kind == "bool":
        if not isinstance(val, bool):
            raise_error("ERR_VALIDATION", f"Field '{name}' must be a boolean")
    elif kind == "array":
        if not isinstance(val, list):
            raise_error("ERR_VALIDATION", f"Field '{name}' must be an array")
    return val


def optional_field(body, name, kind=None, default=None):
    if name not in body or body[name] is None:
        return default
    return require_field(body, name, kind=kind)


def require_enum(body, name, allowed):
    v = require_field(body, name, kind="string")
    if v not in allowed:
        raise_error("ERR_VALIDATION", f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def parse_iso8601(s: str, field_name: str = "timestamp") -> datetime:
    if not isinstance(s, str) or not s:
        raise_error("ERR_VALIDATION", f"{field_name} must be an ISO 8601 string")
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
    except Exception:
        raise_error("ERR_VALIDATION", f"{field_name} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination(req):
    """Parse limit/offset. limit default 10, min 1, max 100; offset default 0, min 0."""
    limit_raw = req.args.get("limit")
    offset_raw = req.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (ValueError, TypeError):
        raise_error("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise_error("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise_error("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def check_version(body, resource):
    """Optimistic concurrency check. PRD §2.6. The body may include a 'version'
    field; if present and the resource has a 'version' field that differs, raise
    ERR_VERSION_MISMATCH (HTTP 412). Missing version in body → skip check."""
    if not isinstance(body, dict):
        return
    if "version" not in body or body["version"] is None:
        return
    if "version" not in resource:
        # Append-only entity; OCC doesn't apply (PRD §2.6).
        return
    if body["version"] != resource["version"]:
        raise_error("ERR_VERSION_MISMATCH",
                    "version in body does not match current resource version")
