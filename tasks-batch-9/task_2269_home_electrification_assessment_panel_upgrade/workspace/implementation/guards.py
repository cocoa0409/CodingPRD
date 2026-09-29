"""Rungs 1, 2 and 4 of the validation ladder: identity, role, pagination."""
from functools import wraps

from flask import g, request

import errors
from errors import ApiError

APPLICANT = "Applicant"
CONTRACTOR = "Contractor"
FIELD_INSPECTOR = "FieldInspector"
PROGRAM_REVIEWER = "ProgramReviewer"
PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (APPLICANT, CONTRACTOR, FIELD_INSPECTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)


def authorize(*allowed_roles):
    """Rung 1 (X-User-ID present) then rung 2 (X-User-Role permitted)."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            if user_id is None or not user_id.strip():
                raise ApiError(errors.ERR_UNAUTHENTICATED)
            role = request.headers.get("X-User-Role")
            if role is None or role not in ALL_ROLES or role not in allowed_roles:
                raise ApiError(errors.ERR_FORBIDDEN_ROLE)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.user_id


def actor_role():
    return g.role


def body():
    """Rung 3 entry point: the request body must parse into a JSON object."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, message="Request body must be a JSON object.")
    return payload


def pagination():
    """Rung 4: limit within [1, 100] and offset >= 0 when supplied."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_PAGINATION)
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_INVALID_PAGINATION)
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_PAGINATION)
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_PAGINATION)
    return limit, offset


def paginate(records, limit, offset):
    return records[offset:offset + limit]


def bool_arg(name):
    """Optional boolean query filter; returns True, False or None."""
    raw = request.args.get(name)
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ApiError(errors.ERR_INVALID_REQUEST, message="%s must be a boolean." % name)
