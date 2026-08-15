"""Auth header extraction, role checking, and request-body validation helpers.

Validation priority (PRD §2.6):
  1. Authentication  (X-User-Role present and a declared role) -> 401
  2. Body shape      (required fields, enums, formats)         -> 400
  3. Authorization   (role permitted; Customer ownership)      -> 403
  4. Existence       (path/body referenced resources, L-to-R)  -> 404
  5. State validity  ... etc.
"""
from __future__ import annotations

import re
from datetime import datetime

from flask import request

from errors import (
    ERR_FORBIDDEN,
    ERR_UNAUTHENTICATED,
    ApiError,
    raise_err,
    validation,
)

ROLES = [
    "Customer",
    "IntakeCoordinator",
    "Inspector",
    "Technician",
    "Certifier",
    "Planner",
    "ServiceManager",
]


class Caller:
    def __init__(self, user_id: str | None, role: str):
        self.user_id = user_id
        self.role = role

    def is_customer(self) -> bool:
        return self.role == "Customer"


def authenticate() -> Caller:
    """Priority 1: X-User-Role header must be present and name a declared role."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise_err(
            ERR_UNAUTHENTICATED,
            "X-User-Role header missing or not a declared role",
        )
    user_id = request.headers.get("X-User-ID")
    return Caller(user_id=user_id, role=role)


def require_roles(caller: Caller, allowed: list[str]):
    """Priority 3 (role part): the caller's role must be permitted."""
    if caller.role not in allowed:
        raise_err(
            ERR_FORBIDDEN,
            f"Role {caller.role} is not permitted to perform this operation",
        )


def require_customer_ownership(caller: Caller, customer_id: str | None):
    """A Customer caller may only act on resources whose customer_id == X-User-ID."""
    if caller.is_customer() and caller.user_id != customer_id:
        raise_err(
            ERR_FORBIDDEN,
            "Customer may only act on its own resources",
        )


# ---------------------------------------------------------------------------
# Body-shape validation helpers (priority 2)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        validation("Request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    val = body.get(name)
    if val is None:
        validation(f"Missing required field: {name}")
    return val


def as_string(body: dict, name: str, required: bool = True) -> str | None:
    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return None
    if not isinstance(val, str) or val == "":
        validation(f"Field {name} must be a non-empty string")
    return val


def as_int(body: dict, name: str, required: bool = True) -> int | None:
    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        validation(f"Field {name} must be an integer")
    return val


def as_number(body: dict, name: str, required: bool = True):
    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        validation(f"Field {name} must be a number")
    return val


def as_bool(body: dict, name: str, default: bool | None = None, required: bool = False):
    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return default
    if not isinstance(val, bool):
        validation(f"Field {name} must be a boolean")
    return val


def as_enum(body: dict, name: str, values: list[str], required: bool = True, default=None):
    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return default
    if not isinstance(val, str) or val not in values:
        validation(f"Field {name} must be one of {values}")
    return val


def as_date(body: dict, name: str, required: bool = True) -> str | None:
    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return None
    if not isinstance(val, str) or not _DATE_RE.match(val):
        validation(f"Field {name} must be a YYYY-MM-DD date")
    try:
        datetime.strptime(val, "%Y-%m-%d")
    except ValueError:
        validation(f"Field {name} must be a valid YYYY-MM-DD date")
    return val


def as_datetime_str(body: dict, name: str, required: bool = True) -> str | None:
    from db import _parse_iso

    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return None
    if not isinstance(val, str):
        validation(f"Field {name} must be an ISO 8601 datetime string")
    try:
        _parse_iso(val)
    except (ValueError, TypeError):
        validation(f"Field {name} must be a valid ISO 8601 datetime")
    return val


def as_array(body: dict, name: str, required: bool = True) -> list | None:
    val = body.get(name)
    if val is None:
        if required:
            validation(f"Missing required field: {name}")
        return None
    if not isinstance(val, list):
        validation(f"Field {name} must be an array")
    return val
