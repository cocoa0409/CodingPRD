"""Per-route helpers: body parsing, RBAC decorators, pagination, fetches."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Iterable

from flask import request

from app import store
from app.auth import Caller, authenticate, require_role
from app.errors import (
    application_not_found,
    bad_request,
    claimant_not_found,
    forbidden,
    invalid_pagination,
    resource_not_found,
)


def get_json_body() -> dict:
    """Return the JSON body or {} when absent. Malformed bodies -> ERR_BAD_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise bad_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def with_auth(*allowed_roles: str) -> Callable:
    """Decorator: authenticate then enforce that the caller's role is allowed."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            caller: Caller = authenticate()
            require_role(caller, allowed_roles)
            kwargs["caller"] = caller
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def parse_pagination() -> tuple[int, int]:
    """Validate and return (limit, offset). Bounds from SCAFFOLD §1.0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_pagination("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_pagination("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_pagination("offset must be an integer")
        if offset < 0:
            raise invalid_pagination("offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset:offset + limit], total


def fetch_claimant(claimant_id: str) -> dict:
    c = store.claimants.get(claimant_id)
    if not c:
        raise claimant_not_found(f"Claimant {claimant_id} not found")
    return c


def fetch_application_under_claimant(claimant_id: str, application_id: str) -> dict:
    a = store.applications.get(application_id)
    if not a:
        raise application_not_found(f"Application {application_id} not found")
    if a["claimant_id"] != claimant_id:
        raise application_not_found(
            f"Application {application_id} does not belong to claimant {claimant_id}"
        )
    return a


def assert_claimant_self_access(caller: Caller, claimant_id: str) -> None:
    """For Claimant role, X-User-ID must equal the URL's claimantId."""
    if caller.role == "Claimant" and caller.user_id != claimant_id:
        raise forbidden("Claimant cannot access another claimant's resources")


def require_field(body: dict, field: str) -> Any:
    if field not in body or body[field] is None:
        raise bad_request(f"Missing required field: {field}")
    return body[field]


def require_string(body: dict, field: str, *, min_length: int = 1) -> str:
    val = require_field(body, field)
    if not isinstance(val, str):
        raise bad_request(f"{field} must be a string")
    if len(val) < min_length:
        raise bad_request(f"{field} must be at least {min_length} characters")
    return val


def require_int(body: dict, field: str) -> int:
    val = require_field(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise bad_request(f"{field} must be an integer")
    return val


def require_enum(body: dict, field: str, allowed: Iterable[str]) -> str:
    val = require_field(body, field)
    allowed_set = set(allowed)
    if val not in allowed_set:
        raise bad_request(
            f"{field} must be one of {sorted(allowed_set)}"
        )
    return val
