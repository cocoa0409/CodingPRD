"""Auth context, role checks, body parsing, field validators, pagination.

Validation pipeline order (PRD section 2.11):
  1. credentials (X-User-ID / X-User-Role)  -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
  2. role authorization                     -> ERR_FORBIDDEN_FOR_ROLE
  3. request-shape validity                 -> ERR_INVALID_REQUEST
  4. path identifier existence (left-right) -> ERR_NOT_FOUND
  5. optimistic concurrency                 -> ERR_STALE_VERSION
  6+. state / business / temporal / fiscal rules, enforced in the routes/services.
"""
from datetime import datetime, timezone

from flask import request

import db
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    raise_err,
)

ROLES = {
    "VendorSpecialist",
    "VendorManager",
    "ComplianceOfficer",
    "APClerk",
    "APSupervisor",
    "APManager",
    "Controller",
    "TreasuryAnalyst",
    "TreasuryManager",
    "BankFileProcessor",
    "Auditor",
    "SystemAdmin",
}

TIER_ROLE = {1: "APSupervisor", 2: "APManager", 3: "Controller"}

ALL_ROLES = sorted(ROLES)


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    """Pipeline step 1: credentials."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
        )
    return Ctx(user_id, role)


def require_role(ctx, allowed):
    """Pipeline step 2: role authorization for the endpoint."""
    if ctx.role not in allowed:
        raise_err(ERR_FORBIDDEN_FOR_ROLE, "Role %s is not authorized for this endpoint." % ctx.role)


def require_tier_role(ctx, tier):
    """Invoice approve/reject finer-grained rule: caller role must equal TIER_ROLE[tier]."""
    if tier not in TIER_ROLE or ctx.role != TIER_ROLE[tier]:
        raise_err(
            ERR_FORBIDDEN_FOR_ROLE,
            "Role %s is not the designated role for tier %s." % (ctx.role, tier),
        )


def get_body(required=True):
    """Pipeline step 3 (parse leg): body must be a JSON object when required."""
    if not request.data:
        if required:
            raise_err(ERR_INVALID_REQUEST, "Request body is required.")
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


# --- field validators (pipeline step 3) ---

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a string." % field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a string." % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None or not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be an integer." % field)
    return v


def opt_int(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % field)
    return v


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a number." % field)
    return v


def opt_number(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a number." % field)
    return v


def parse_iso_date(value, field):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO date string." % field)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO date string (YYYY-MM-DD)." % field)


def parse_iso_instant(value, field):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 timestamp string." % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 timestamp string." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- existence (pipeline step 4) ---

def get_or_404(store, entity_id, label="Resource"):
    rec = store.get(entity_id)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "%s '%s' does not exist." % (label, entity_id))
    return rec


# --- pagination (PRD section 2.3) ---

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer.")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer.")
        offset = max(0, offset)
    return limit, offset


def paginate(items):
    """Sort by created_at ascending (stable: insertion order breaks ties), then page."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda r: r["created_at"])
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total, limit, offset
