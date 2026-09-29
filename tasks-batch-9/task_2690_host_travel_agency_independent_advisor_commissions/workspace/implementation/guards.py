"""Authentication, authorization, request-shape validation and pagination.

PRD 2.1 fixes the header names (X-User-ID / X-User-Role) and the five role
names; PRD 2.8 fixes the order in which a request is rejected.
"""

import re

from flask import request

from errors import ApiError
from store import parse_iso8601

ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor", "SupplierPortal")

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_advisor(self):
        return self.role == "Advisor"

    @property
    def is_supplier(self):
        return self.role == "SupplierPortal"


def authenticate(allowed_roles):
    """PRD 2.8 steps 1 and 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Caller(user_id, role)


# --------------------------------------------------------------------------
# request body (PRD 2.8 step 3)
# --------------------------------------------------------------------------

def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def read_body(allowed_fields, required_body=True):
    """Return the request body as a dict, rejecting unknown fields."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required_body:
            _bad("A JSON object request body is required.")
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        _bad("The request body must be a JSON object.")
    for key in body.keys():
        if key not in allowed_fields:
            _bad("Unknown field: %s" % key)
    return body


def has(body, name):
    return name in body and body[name] is not None


def _present(body, name, required):
    if name not in body:
        if required:
            _bad("Missing required field: %s" % name)
        return False
    if body[name] is None:
        if required:
            _bad("Field %s may not be null." % name)
        return False
    return True


def field_str(body, name, required=True, default=None, allow_empty=False, max_len=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad("Field %s must be a string." % name)
    if not allow_empty and value == "":
        _bad("Field %s must be non-empty." % name)
    if max_len is not None and len(value) > max_len:
        _bad("Field %s exceeds %d characters." % (name, max_len))
    return value


def field_state_code(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = field_str(body, name, required=True)
    if not STATE_CODE_RE.match(value):
        _bad("Field %s must be exactly two uppercase letters." % name)
    return value


def field_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("Field %s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Field %s must be <= %s." % (name, maximum))
    return value


def field_number(body, name, required=True, default=None,
                 minimum=None, maximum=None, exclusive_min=False, exclusive_max=False):
    if not _present(body, name, required):
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field %s must be a number." % name)
    value = float(value)
    if minimum is not None:
        if exclusive_min and not value > minimum:
            _bad("Field %s must be > %s." % (name, minimum))
        if not exclusive_min and value < minimum:
            _bad("Field %s must be >= %s." % (name, minimum))
    if maximum is not None:
        if exclusive_max and not value < maximum:
            _bad("Field %s must be < %s." % (name, maximum))
        if not exclusive_max and value > maximum:
            _bad("Field %s must be <= %s." % (name, maximum))
    return value


def field_enum(body, name, members, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in members:
        _bad("Field %s must be one of %s." % (name, ", ".join(members)))
    return value


def field_dt(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    parsed = parse_iso8601(value) if isinstance(value, str) else None
    if parsed is None:
        _bad("Field %s must be an ISO 8601 instant." % name)
    return parsed


def field_list(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, list):
        _bad("Field %s must be an array." % name)
    return value


def field_object_keys(obj, name, required_keys):
    if not isinstance(obj, dict):
        _bad("Each entry of %s must be an object." % name)
    for key in required_keys:
        if key not in obj or obj[key] is None:
            _bad("Each entry of %s requires %s." % (name, key))
    for key in obj.keys():
        if key not in required_keys:
            _bad("Unknown field in %s entry: %s" % (name, key))


def entry_int(obj, name, field, minimum=None):
    value = obj[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s.%s must be an integer." % (name, field))
    if minimum is not None and value < minimum:
        _bad("%s.%s must be >= %s." % (name, field, minimum))
    return value


def entry_number(obj, name, field, minimum=None, maximum=None,
                 exclusive_min=False, exclusive_max=False):
    value = obj[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("%s.%s must be a number." % (name, field))
    value = float(value)
    if minimum is not None:
        if exclusive_min and not value > minimum:
            _bad("%s.%s must be > %s." % (name, field, minimum))
        if not exclusive_min and value < minimum:
            _bad("%s.%s must be >= %s." % (name, field, minimum))
    if maximum is not None:
        if exclusive_max and not value < maximum:
            _bad("%s.%s must be < %s." % (name, field, maximum))
        if not exclusive_max and value > maximum:
            _bad("%s.%s must be <= %s." % (name, field, maximum))
    return value


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not re.match(r"^-?\d+$", raw_limit.strip()):
            _bad("limit must be an integer.")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            _bad("limit must be between 1 and 100.")
    if raw_offset is not None:
        if not re.match(r"^-?\d+$", raw_offset.strip()):
            _bad("offset must be an integer.")
        offset = int(raw_offset)
        if offset < 0:
            _bad("offset may not be negative.")
    return limit, offset


def slice_page(rows, limit, offset):
    return rows[offset:offset + limit]


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
