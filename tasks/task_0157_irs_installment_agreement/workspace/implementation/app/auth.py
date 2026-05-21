"""Authentication / RBAC helpers.

Reads X-User-ID and X-User-Role headers per SCAFFOLD.yaml validation priority 1
and PRD §2.1. Supplies an `Identity` object and decorators for role gates.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Iterable

from flask import request

from app.errors import ERR_AUTH_REQUIRED, ERR_FORBIDDEN, raise_error


VALID_ROLES = {"Taxpayer", "IRSOfficer", "OICOfficer"}


@dataclass(frozen=True)
class Identity:
    user_id: str
    role: str


def get_identity() -> Identity:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error(ERR_AUTH_REQUIRED, "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise_error(ERR_AUTH_REQUIRED, f"Unrecognized role: {role!r}.")
    if not isinstance(user_id, str) or not user_id.strip():
        raise_error(ERR_AUTH_REQUIRED, "Malformed X-User-ID header.")
    return Identity(user_id=user_id, role=role)


def require_roles(*allowed: str):
    """Decorator: enforce role membership.

    Auth header presence is checked first (ERR_AUTH_REQUIRED, priority 1);
    role membership in the allowed set is checked second (ERR_FORBIDDEN, priority 3).
    """
    allowed_set = set(allowed)

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            identity = get_identity()
            if identity.role not in allowed_set:
                raise_error(ERR_FORBIDDEN, f"Role {identity.role!r} is not allowed for this endpoint.")
            return fn(identity, *args, **kwargs)

        return wrapper

    return deco


def enforce_taxpayer_ownership(identity: Identity, owner_taxpayer_id: str):
    """When acting as Taxpayer, the X-User-ID must equal the resource's taxpayer_id."""
    if identity.role == "Taxpayer" and identity.user_id != owner_taxpayer_id:
        raise_error(ERR_FORBIDDEN, "Taxpayer may only act on their own resources.")
