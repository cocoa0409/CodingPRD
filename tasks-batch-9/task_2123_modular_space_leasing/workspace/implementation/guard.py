"""The screening ladder (PRD 2.9): auth, role, existence, body shape, ownership."""
from flask import request

from errors import ApiError, invalid
from calc import parse_iso_date
import db

ROLES = ("FleetAdmin", "BranchOps", "LeasingAgent", "DamageAssessor", "Customer")


# ---- rank 1 + 2 -----------------------------------------------------------

def auth(*allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and a recognised X-User-Role header are required.")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Role %s may not perform this operation." % role)
    return user_id, role


# ---- rank 3 + 4 -----------------------------------------------------------

def lookup(collection, identifier, error_id):
    record = collection.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(error_id, "Referenced resource %r does not exist." % (identifier,))
    return record


def resolve_fk(body, field, collection, error_id, required=True):
    """Rank 4: resolve a body foreign key.

    A missing / non-string value is left for the rank-5 body-shape check.
    """
    value = body.get(field)
    if value is None or not isinstance(value, str) or value == "":
        return None
    return lookup(collection, value, error_id)


# ---- rank 5 ---------------------------------------------------------------

def get_body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        invalid("Request body must be a JSON object.")
    return raw


def _present(body, key):
    return key in body and body[key] is not None


def v_string(body, key, required=True, default=None, allow_blank=False):
    if not _present(body, key):
        if required:
            invalid("'%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        invalid("'%s' must be a string." % key)
    if not allow_blank and value.strip() == "":
        invalid("'%s' may not be blank." % key)
    return value


def v_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("'%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        invalid("'%s' must be a boolean." % key)
    return value


def v_int(body, key, required=True, default=None, minimum=None, maximum=None, choices=None):
    if not _present(body, key):
        if required:
            invalid("'%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("'%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        invalid("'%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("'%s' must be <= %s." % (key, maximum))
    if choices is not None and value not in choices:
        invalid("'%s' must be one of %s." % (key, list(choices)))
    return value


def v_number(body, key, required=True, default=None, minimum=None, maximum=None, exclusive_minimum=None):
    if not _present(body, key):
        if required:
            invalid("'%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("'%s' must be a number." % key)
    if minimum is not None and value < minimum:
        invalid("'%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("'%s' must be <= %s." % (key, maximum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        invalid("'%s' must be > %s." % (key, exclusive_minimum))
    return value


def v_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("'%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        invalid("'%s' must be one of %s." % (key, list(allowed)))
    return value


def v_date(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("'%s' is required." % key)
        return default
    value = body[key]
    parsed = parse_iso_date(value) if isinstance(value, str) else None
    if parsed is None:
        invalid("'%s' must be an ISO yyyy-mm-dd date." % key)
    return parsed


def v_id(body, key, required=True):
    """Body foreign-key shape check (existence already handled at rank 4)."""
    return v_string(body, key, required=required)


# ---- rank 6 ---------------------------------------------------------------

def require_branch_owner(user_id, role, branch_id):
    if role == "BranchOps" and user_id != branch_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The acting branch does not own this resource.")


def require_customer_owner(user_id, role, customer_id):
    if role == "Customer" and user_id != customer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The acting customer does not own this resource.")
