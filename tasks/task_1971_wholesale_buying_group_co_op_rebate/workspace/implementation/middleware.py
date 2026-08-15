"""Auth context extraction and role authorization (PRD §2.1, §2.9 checks 1-2)."""

import functools

from flask import request

from errors import err_missing_context, err_forbidden

ROLES = {"CoopAdmin", "MemberRep", "SupplierRep", "FinanceOfficer", "ProgramAuditor"}


def get_auth():
    """Validate X-User-ID / X-User-Role presence and well-formedness.

    MemberRep => X-User-ID is a Member id; SupplierRep => a Supplier id;
    the other three roles carry opaque operator identifiers (PRD §2.1).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        raise err_missing_context()
    if not isinstance(uid, str) or not uid.strip():
        raise err_missing_context()
    if not isinstance(role, str) or role not in ROLES:
        raise err_missing_context()
    return uid.strip(), role


def require_roles(*allowed):
    """Decorator: pipeline check 1 (user context) then check 2 (role)."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = get_auth()
            if role not in allowed:
                raise err_forbidden()
            return fn(uid, role, *args, **kwargs)
        return wrapper
    return decorator


def body_json(required=False):
    """Return the request JSON body as a dict; {} when absent.

    A present but unparsable or non-object body fails schema validation.
    """
    if request.content_length in (None, 0) and not request.data:
        if required:
            raise err_missing_body()
        return {}
    data = request.get_json(silent=True)
    if data is None or isinstance(data, bool) or not isinstance(data, dict):
        from errors import err_invalid_request
        raise err_invalid_request("Request body must be a JSON object")
    return data


def err_missing_body():
    from errors import err_invalid_request
    return err_invalid_request("Request body is required")


def req_str(body, field):
    from errors import err_invalid_request
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request("Field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field, default=None):
    from errors import err_invalid_request
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err_invalid_request("Field '%s' must be a string" % field)
    return v


def req_int(body, field, minimum=None):
    from errors import err_invalid_request
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request("Field '%s' is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err_invalid_request("Field '%s' must be >= %d" % (field, minimum))
    return v


def opt_int(body, field, default=None):
    from errors import err_invalid_request
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request("Field '%s' must be an integer" % field)
    return v


def req_bool(body, field):
    from errors import err_invalid_request
    v = body.get(field)
    if not isinstance(v, bool):
        raise err_invalid_request("Field '%s' is required and must be a boolean" % field)
    return v


def opt_bool(body, field, default=None):
    from errors import err_invalid_request
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err_invalid_request("Field '%s' must be a boolean" % field)
    return v
