"""Auth header extraction, RBAC gate, request-shape validators, pagination.

The validation ladder of PRD section 2.10 is realised by calling these helpers in
rung order from each route handler.
"""

from flask import request

from db import db, parse_day, parse_instant
from errors import ApiError
from response import (
    LIMIT_DEFAULT,
    LIMIT_MAX,
    LIMIT_MIN,
    LIMIT_PARAM,
    OFFSET_DEFAULT,
    OFFSET_MIN,
    OFFSET_PARAM,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_LEAD = "LeadAssessor"
ROLE_ASSESSOR = "Assessor"
ROLE_QA = "QaReviewer"
ROLE_VENDOR = "AsvVendor"
ROLE_CLIENT = "ClientRepresentative"
ROLE_ADMIN = "PlatformAdmin"

ALL_ROLES = (ROLE_LEAD, ROLE_ASSESSOR, ROLE_QA, ROLE_VENDOR, ROLE_CLIENT, ROLE_ADMIN)
ASSESSOR_ROLES = (ROLE_LEAD, ROLE_ASSESSOR, ROLE_QA)
OPAQUE_ROLES = (ROLE_CLIENT, ROLE_ADMIN)


# --------------------------------------------------------------------------- #
# Rung 1 + 2: authentication and authorization
# --------------------------------------------------------------------------- #
def authenticate(allowed_roles):
    """Resolve the caller (rung 1) then gate the role (rung 2)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role in ASSESSOR_ROLES:
        if user_id not in db.assessors:
            raise ApiError("ERR_UNAUTHENTICATED")
    elif role == ROLE_VENDOR:
        if user_id not in db.asv_vendors:
            raise ApiError("ERR_UNAUTHENTICATED")
    # ClientRepresentative and PlatformAdmin identities stay opaque; any
    # non-empty value is recognised and is never compared with a stored row.
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------- #
# Rung 3: request shape
# --------------------------------------------------------------------------- #
def json_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def present(body, field):
    if field not in body or body[field] is None:
        _bad(field, "is required")
    return body[field]


def v_str(body, field, required=True, allow_empty=True, default=None):
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and not value.strip():
        _bad(field, "must not be empty")
    return value


def v_enum(body, field, domain, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, str) or value not in domain:
        _bad(field, "must be one of %s" % ", ".join(domain))
    return value


def v_int(body, field, required=True, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def v_number(body, field, required=True, minimum=None, maximum=None,
             exclusive_minimum=None, default=None):
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    if exclusive_minimum is not None and not value > exclusive_minimum:
        _bad(field, "must be greater than %s" % exclusive_minimum)
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def v_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def v_day(body, field, required=True, default=None):
    """Strict YYYY-MM-DD; returns (raw_string, date)."""
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default, None
    raw = body[field]
    if not isinstance(raw, str):
        _bad(field, "must be a YYYY-MM-DD string")
    day = parse_day(raw)
    if day is None:
        _bad(field, "must be a YYYY-MM-DD date")
    return raw, day


def v_instant(body, field, required=True, default=None):
    """ISO-8601 instant; returns (raw_string, datetime)."""
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default, None
    raw = body[field]
    if not isinstance(raw, str):
        _bad(field, "must be an ISO-8601 timestamp string")
    moment = parse_instant(raw)
    if moment is None:
        _bad(field, "must be an ISO-8601 timestamp")
    return raw, moment


def v_str_array(body, field, required=True, min_items=1, default=None):
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, list):
        _bad(field, "must be an array of strings")
    if len(value) < min_items:
        _bad(field, "must contain at least %d entry" % min_items)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad(field, "must contain only non-empty strings")
    return list(value)


def v_id_ref(body, field, required=True, default=None):
    """A reference field: must be a string when supplied."""
    if field not in body or body[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        _bad(field, "must be a non-empty id string")
    return value


# --------------------------------------------------------------------------- #
# Rung 3 (query string) + list plumbing
# --------------------------------------------------------------------------- #
def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if LIMIT_PARAM in request.args:
        raw = request.args.get(LIMIT_PARAM)
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad(LIMIT_PARAM, "must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            _bad(LIMIT_PARAM, "must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if OFFSET_PARAM in request.args:
        raw = request.args.get(OFFSET_PARAM)
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad(OFFSET_PARAM, "must be an integer")
        if offset < OFFSET_MIN:
            _bad(OFFSET_PARAM, "must be >= %d" % OFFSET_MIN)
    return limit, offset


def _bool_arg(raw):
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def apply_filters(rows, spec):
    """spec: {query_param: (field_name, kind)} with kind in {'str','bool','int'}."""
    result = rows
    for param, (field, kind) in spec.items():
        if param not in request.args:
            continue
        raw = request.args.get(param)
        if kind == "bool":
            wanted = _bool_arg(raw)
            if wanted is None:
                result = []
                continue
            result = [row for row in result if bool(row.get(field)) is wanted]
        elif kind == "int":
            try:
                wanted_int = int(str(raw).strip())
            except (TypeError, ValueError):
                _bad(param, "must be an integer")
            result = [row for row in result if row.get(field) == wanted_int]
        else:
            result = [row for row in result if row.get(field) == raw]
    return result


def page(rows, limit, offset):
    return rows[offset:offset + limit]


# --------------------------------------------------------------------------- #
# Rung 4 / 5: existence
# --------------------------------------------------------------------------- #
def fetch(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


# --------------------------------------------------------------------------- #
# Rung 6: ownership
# --------------------------------------------------------------------------- #
def require_lead(engagement, user_id):
    if engagement.get("lead_assessor_id") != user_id:
        raise ApiError("ERR_NOT_ENGAGEMENT_LEAD")


def require_qa_reviewer(engagement, user_id):
    if not engagement.get("qa_reviewer_id") or engagement.get("qa_reviewer_id") != user_id:
        raise ApiError("ERR_NOT_ENGAGEMENT_QA_REVIEWER")


def require_cycle_vendor(cycle, user_id):
    if cycle.get("asv_vendor_id") != user_id:
        raise ApiError("ERR_VENDOR_SCOPE_FORBIDDEN")
