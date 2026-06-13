"""Auth extraction, RBAC, and shared request helpers.

Headers (PRD §2.1): X-User-ID and X-User-Role are mandatory on every request.
Roles, spelled exactly: ClinicAdmin, Audiologist, BillingClerk, Patient.
"""

from flask import request

import errors

KNOWN_ROLES = {"ClinicAdmin", "Audiologist", "BillingClerk", "Patient"}


class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    """Validate the auth headers (priority 1). Returns an Auth object or raises
    ERR_UNAUTHENTICATED (401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in KNOWN_ROLES:
        raise errors.unauthenticated("Unknown role.")
    return Auth(user_id, role)


def require_role(auth, allowed_roles):
    """Role-permission check (priority 2). Raises ERR_FORBIDDEN (403) if the
    acting role is not in the allowed set for the endpoint."""
    if auth.role not in allowed_roles:
        raise errors.forbidden()


def require_ownership(auth, owner_patient_id):
    """Patient ownership check (priority 3, PRD §2.1).

    When the acting role is Patient, X-User-ID must equal the resource's
    patient_id. Operators (ClinicAdmin/Audiologist/BillingClerk) are never
    subject to this check. Evaluated AFTER the role-permission check.
    """
    if auth.role == "Patient" and auth.user_id != owner_patient_id:
        raise errors.forbidden("Patient does not own this resource.")


def get_json_body():
    """Return the parsed JSON body as a dict. A malformed or non-object body is
    ERR_INVALID_REQUEST (400). A missing body is treated as an empty object so
    that no-body action endpoints work."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def parse_pagination(args):
    """Parse and validate limit/offset (PRD §2.3).

    Defaults: limit=10 (min 1, max 100), offset=0 (>= 0). Out-of-range ->
    ERR_VALIDATION_LIMIT (422). Non-integer -> ERR_VALIDATION_LIMIT too, since
    these are pagination params.
    """
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.validation_limit("limit must be an integer.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.validation_limit("offset must be an integer.")
    if limit < 1 or limit > 100:
        raise errors.validation_limit("limit must be between 1 and 100.")
    if offset < 0:
        raise errors.validation_limit("offset must not be negative.")
    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list and return (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
