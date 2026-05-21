"""Per-route helpers: body parsing, query helpers, role decorators."""

from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import request

from app.auth import Caller, authenticate, require_role


def get_json_body() -> dict:
    """Return the JSON body or {} when absent.

    Wrong-shape bodies raise the global Flask 400 handler, which maps to
    ERR_VALIDATION/422.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        from app.errors import validation
        raise validation("Request body must be valid JSON")
    if body is None:
        return {}
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


def query_bool(name: str):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.lower() in ("true", "1", "yes"):
        return True
    if raw.lower() in ("false", "0", "no"):
        return False
    from app.errors import validation
    raise validation(f"{name} must be boolean")


def query_int(name: str):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        from app.errors import validation
        raise validation(f"{name} must be an integer")
