"""Auth header extraction and role checking (PRD §2.1, validations 1-2)."""

from flask import request
from errors import (
    ApiError,
    ERR_MISSING_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    raise_err,
)

VALID_ROLES = {"FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client"}
ENTITY_BACKED = {"TaxAnalyst", "SeniorManager", "Client"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller(store):
    """Validation priority 1: both headers present, role recognized, and
    entity-backed identifiers resolvable."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_MISSING_CONTEXT_HEADER, "X-User-ID and X-User-Role headers are required")
    if role not in VALID_ROLES:
        raise_err(ERR_MISSING_CONTEXT_HEADER, f"Unrecognized role: {role}")
    if role in ("TaxAnalyst", "SeniorManager"):
        if user_id not in store.operators:
            raise_err(ERR_MISSING_CONTEXT_HEADER, "X-User-ID does not resolve to an Operator")
    elif role == "Client":
        if user_id not in store.clients:
            raise_err(ERR_MISSING_CONTEXT_HEADER, "X-User-ID does not resolve to a ClientAccount")
    return Caller(user_id, role)


def require_role(caller, *roles):
    """Validation priority 2: role permitted for the endpoint."""
    if caller.role not in roles:
        raise_err(ERR_FORBIDDEN_ROLE, f"Role {caller.role} is not permitted for this endpoint")


def parse_pagination():
    """Parse limit/offset query params with scaffold defaults (limit default
    10, min 1, max 100; offset default 0)."""
    from errors import ERR_INVALID_REQUEST
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
