"""Auth extraction, RBAC, ownership checks, and request-field validators.

Auth scheme (PRD §2.1): every request carries X-User-ID and X-User-Role.
Roles: OpsAdmin, Dispatcher, Driver, BillingAdmin, CustomerSelf.
The logical-clock endpoint is exempt from header presence checks.
"""
import re
from functools import wraps

from flask import g, request

import errors
from errors import ApiError

ROLES = {"OpsAdmin", "Dispatcher", "Driver", "BillingAdmin", "CustomerSelf"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- auth / rbac

def extract_auth():
    """Validation priority 1: header presence + well-formedness."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise errors.unauthenticated()
    g.user_id = uid
    g.role = role


def require_roles(*roles):
    """Validation priority 2: role permission for the endpoint."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in roles:
                raise errors.unauthorized()
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_owner(customer_id):
    """Priority 15: CustomerSelf may only touch own resources."""
    if g.role == "CustomerSelf" and g.user_id != customer_id:
        raise errors.forbidden(
            "CustomerSelf attempted to act on a resource whose customer_id "
            "does not equal X-User-ID")


# ------------------------------------------------------------ body validation

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("request body must be a JSON object")
    return data


def f_str(d, key, required=True, default=None):
    v = d.get(key, None)
    if v is None:
        if required:
            raise errors.invalid_request(f"required field missing: {key}")
        return default
    if not isinstance(v, str):
        raise errors.invalid_request(f"field {key} must be a string")
    return v


def f_int(d, key, required=True, default=None, min_value=None):
    v = d.get(key, None)
    if v is None:
        if required:
            raise errors.invalid_request(f"required field missing: {key}")
        return default
    if not isinstance(v, int) or isinstance(v, bool):
        raise errors.invalid_request(f"field {key} must be an integer")
    if min_value is not None and v < min_value:
        raise errors.invalid_request(f"field {key} must be >= {min_value}")
    return v


def f_enum(d, key, allowed, required=True, default=None):
    v = d.get(key, None)
    if v is None:
        if required:
            raise errors.invalid_request(f"required field missing: {key}")
        return default
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            f"field {key} must be one of {sorted(allowed)}")
    return v


def f_bool(d, key, required=False, default=None):
    v = d.get(key, None)
    if v is None:
        if required:
            raise errors.invalid_request(f"required field missing: {key}")
        return default
    if not isinstance(v, bool):
        raise errors.invalid_request(f"field {key} must be a boolean")
    return v


def f_date(d, key, required=True):
    """Date fields: missing/wrong type -> 400; malformed value -> 422."""
    v = d.get(key, None)
    if v is None:
        if required:
            raise errors.invalid_request(f"required field missing: {key}")
        return None
    if not isinstance(v, str):
        raise errors.invalid_request(f"field {key} must be a string")
    if not _DATE_RE.match(v):
        raise errors.invalid_date_range(f"field {key} is not a valid YYYY-MM-DD date")
    import datetime as _dt
    try:
        return _dt.datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise errors.invalid_date_range(f"field {key} is not a valid calendar date")


# --------------------------------------------------------------- state checks

def check_transition(record, status_field, valid_from, terminal_states, label):
    """Stage 4: terminal state -> ERR_ALREADY_TERMINAL; otherwise bad state ->
    ERR_INVALID_STATE."""
    cur = record[status_field]
    if cur in valid_from:
        return
    if cur in terminal_states:
        raise errors.already_terminal(
            f"{label} is already in terminal state {cur}")
    raise errors.invalid_state(
        f"{label} in state {cur} does not permit this transition")
