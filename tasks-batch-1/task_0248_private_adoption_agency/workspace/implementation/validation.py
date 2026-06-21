"""Request-body field validation helpers (priority 6: ERR_INVALID_REQUEST)."""
import errors


def get_body(req):
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST if malformed.

    A missing/empty body is treated as an empty dict so that required-field
    checks produce ERR_INVALID_REQUEST consistently.
    """
    if req.content_length in (None, 0) and not (req.data or b"").strip():
        return {}
    try:
        body = req.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # Distinguish truly empty from malformed: empty body => {}.
        raw = (req.data or b"").strip()
        if not raw:
            return {}
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field '%s' is required and must be a non-empty string." % field)
    return val


def require_int(body, field, minimum=None, exclusive_min=None):
    val = body.get(field)
    # bool is a subclass of int; reject it explicitly.
    if not isinstance(val, int) or isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field '%s' is required and must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field '%s' must be >= %s." % (field, minimum))
    if exclusive_min is not None and val <= exclusive_min:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field '%s' must be > %s." % (field, exclusive_min))
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return val


def require_datetime(body, field):
    from timeutil import parse_iso
    val = body.get(field)
    dt = parse_iso(val)
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field '%s' is required and must be an ISO 8601 datetime." % field)
    return dt


def optional_string(body, field):
    """Return a present string field or None when absent. Reject non-string present values."""
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str) or not val.strip():
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field '%s' must be a non-empty string when provided." % field)
    return val
