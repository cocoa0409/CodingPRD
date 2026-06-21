"""Auth extraction and validation helpers.

PRD section 2.1: every request must carry two mandatory headers, X-User-ID and
X-User-Role. A missing or malformed value yields ERR_UNAUTHENTICATED.
Recognized roles: Debtor, Trustee, Creditor, BankruptcyAdmin.
"""

from flask import request

import db
import errors
from errors import err

VALID_ROLES = {"Debtor", "Trustee", "Creditor", "BankruptcyAdmin"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED.

    PRD 2.1: a request missing either header, or carrying a malformed value, is
    rejected with ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header.")
    return user_id, role


def authorize(role, allowed_roles):
    """PRD 2.1 / validations[priority=2]: role must be permitted for the op."""
    if role not in allowed_roles:
        raise err(errors.ERR_UNAUTHORIZED, "Role %s is not permitted for this operation." % role)


# ----- existence helpers (ERR_NOT_FOUND for path ids) -----

def require_path(collection, resource_id):
    """Look up a path-referenced resource; ERR_NOT_FOUND if missing.

    PRD 2.6: path ids validated left to right; first that does not resolve
    produces ERR_NOT_FOUND.
    """
    obj = collection.get(resource_id)
    if obj is None:
        raise err(errors.ERR_NOT_FOUND, "Resource %s not found." % resource_id)
    return obj


def require_fk(collection, fk_value):
    """Look up a body foreign key; ERR_FK_NOT_FOUND if missing.

    PRD 2.6: body FK that resolves to nothing produces ERR_FK_NOT_FOUND.
    """
    obj = collection.get(fk_value)
    if obj is None:
        raise err(errors.ERR_FK_NOT_FOUND, "Referenced resource %s not found." % fk_value)
    return obj


# ----- body/field validation (ERR_INVALID_REQUEST) -----

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def invalid(message):
    raise err(errors.ERR_INVALID_REQUEST, message)


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        invalid("Field %s must be a non-empty string." % field)
    return val


def require_enum(body, field, domain):
    val = body.get(field)
    if not isinstance(val, str) or val not in domain:
        invalid("Field %s must be one of %s." % (field, sorted(domain)))
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        invalid("Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        invalid("Field %s must be >= %d." % (field, minimum))
    if maximum is not None and val > maximum:
        invalid("Field %s must be <= %d." % (field, maximum))
    return val


def optional_int(body, field, default=0, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        invalid("Field %s must be a boolean." % field)
    return val


# ----- pagination (PRD 2.3) -----

def parse_pagination():
    """limit defaults 10, min 1, max 100; offset defaults 0, min 0.

    Malformed pagination values are rejected with ERR_INVALID_REQUEST.
    """
    from flask import request as flask_request

    limit_raw = flask_request.args.get("limit")
    offset_raw = flask_request.args.get("offset")

    limit = 10
    offset = 0

    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            invalid("limit must be an integer.")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100.")

    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            invalid("offset must be an integer.")
        if offset < 0:
            invalid("offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD 2.3) then apply offset/limit."""
    ordered = sorted(items, key=lambda o: (o["created_at"], o["id"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
