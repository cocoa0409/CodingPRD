"""Body-field validation helpers (ERR_VALIDATION, PRD §2.5)."""
import errors


def get_body(req):
    """Return the JSON body as a dict, or {} when absent/empty.

    A malformed JSON body for a request that requires fields is a validation
    error; an empty body is treated as {}.
    """
    if not req.data:
        return {}
    try:
        body = req.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"{field} is required and must be a non-empty string")
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    # bool is a subclass of int; reject it as a wrong type.
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise errors.validation(f"{field} must be >= {minimum}")
    return v


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.validation(f"{field} must be >= {minimum}")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.validation(f"{field} must be a boolean")
    return v


def require_enum(body, field, choices):
    v = body.get(field)
    if not isinstance(v, str) or v not in choices:
        raise errors.validation(f"{field} is required and must be one of {sorted(choices)}")
    return v


def optional_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in choices:
        raise errors.validation(f"{field} must be one of {sorted(choices)}")
    return v


_DATE_RE = None


def require_date(body, field):
    import re
    global _DATE_RE
    if _DATE_RE is None:
        _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    v = body.get(field)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise errors.validation(f"{field} is required and must be a YYYY-MM-DD date")
    return v


def optional_date_list(body, field, default):
    import re
    if field not in body or body[field] is None:
        return list(default)
    v = body[field]
    if not isinstance(v, list):
        raise errors.validation(f"{field} must be a list of YYYY-MM-DD dates")
    rx = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for entry in v:
        if not isinstance(entry, str) or not rx.match(entry):
            raise errors.validation(f"{field} entries must be YYYY-MM-DD dates")
    return list(v)
