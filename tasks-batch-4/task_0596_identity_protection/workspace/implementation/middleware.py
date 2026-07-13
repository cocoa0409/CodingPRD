"""Auth, RBAC, existence, ownership and body-schema helpers.

Validation precedence is normative (PRD §2.5):
  1 auth -> 2 role -> 3 existence (path L-to-R, then body FKs) -> 4 ownership
  -> 5 body schema -> 6 verification token -> 7 OCC -> 8 state legality
  -> 9 cross-entity state -> 10 enrollment gate -> 11.. business rules
Each route calls these helpers in that order.
"""

import re

from flask import request

from db import db, parse_dt
from errors import ApiError

ROLES = (
    "Anonymous",
    "Subscriber",
    "RestorationSpecialist",
    "ClaimsAdjuster",
    "PlatformAdmin",
)

SSN_RE = re.compile(r"^\d{4}$")


# --------------------------------------------------------------------------
# 1. Authentication / 2. Role authorisation
# --------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or unknown.")
    if role != "Anonymous" and (user_id is None or user_id == ""):
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required for role %s." % role)
    return role, user_id


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)


def auth(*allowed):
    role, user_id = authenticate()
    authorize(role, allowed)
    return role, user_id


# --------------------------------------------------------------------------
# 3. Existence
# --------------------------------------------------------------------------
_NOT_FOUND = {
    "plans": "ERR_PLAN_NOT_FOUND",
    "subscribers": "ERR_SUBSCRIBER_NOT_FOUND",
    "family_members": "ERR_FAMILY_MEMBER_NOT_FOUND",
    "bureau_profiles": "ERR_BUREAU_PROFILE_NOT_FOUND",
    "alerts": "ERR_ALERT_NOT_FOUND",
    "cases": "ERR_CASE_NOT_FOUND",
    "specialists": "ERR_SPECIALIST_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "wallet_items": "ERR_WALLET_ITEM_NOT_FOUND",
    "engagements": "ERR_CASE_NOT_FOUND",
    "thaw_windows": "ERR_BUREAU_PROFILE_NOT_FOUND",
}


def must_exist(collection, row_id):
    store = getattr(db, collection)
    row = store.get(row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection], "%s not found." % row_id)
    return row


def must_exist_fk(collection, body, field):
    """Resolve a body FK. A missing / non-string value is left to the body-schema
    stage (priority 5) so it surfaces as ERR_INVALID_REQUEST, not a 404."""
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    return must_exist(collection, value)


# --------------------------------------------------------------------------
# 4. Ownership
# --------------------------------------------------------------------------
def require_subscriber_owner(role, user_id, subscriber_id):
    if role == "Subscriber" and user_id != subscriber_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This resource belongs to another subscriber.")


def require_specialist_owner(role, user_id, specialist_id):
    if role == "RestorationSpecialist" and user_id != specialist_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This resource is not assigned to you.")


# --------------------------------------------------------------------------
# 10. Enrollment gate (PRD §2.7)
# --------------------------------------------------------------------------
def require_enrollment_active(subscriber):
    if subscriber["enrollment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE",
            "The owning subscriber's enrollment is not ACTIVE.",
        )


# --------------------------------------------------------------------------
# 5. Body schema
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s is required and must be a non-empty string." % field)
    return value


def req_enum(data, field, allowed):
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "%s must be one of %s." % (field, " | ".join(allowed)),
        )
    return value


def opt_enum(data, field, allowed, default):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s is required and must be an integer." % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be <= %d." % (field, maximum))
    return value


def opt_int(data, field, default, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum)


def opt_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean." % field)
    return value


def req_ssn_last4(data, field="ssn_last4"):
    value = data.get(field)
    if not isinstance(value, str) or not SSN_RE.match(value):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be exactly four decimal digits." % field)
    return value


def req_datetime(data, field):
    value = data.get(field)
    parsed = parse_dt(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant." % field)
    return parsed


EXPENSE_CATEGORIES = (
    "LEGAL_FEES",
    "LOST_WAGES",
    "TRAVEL",
    "CHILDCARE",
    "NOTARY",
    "POSTAGE",
)


def req_expenses(data, field="expenses"):
    value = data.get(field)
    if not isinstance(value, list) or len(value) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "expenses must be a non-empty array.")
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each expense must be an object.")
        category = item.get("category")
        if not isinstance(category, str) or category not in EXPENSE_CATEGORIES:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "expense category must be one of %s." % " | ".join(EXPENSE_CATEGORIES),
            )
        amount = item.get("amount_cents")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "expense amount_cents must be a positive integer.")
        documented = item.get("documented")
        if not isinstance(documented, bool):
            raise ApiError("ERR_INVALID_REQUEST", "expense documented must be a boolean.")
        cleaned.append(
            {"category": category, "amount_cents": amount, "documented": documented}
        )
    return cleaned
