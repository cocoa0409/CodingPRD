"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 priority 1-2).

Headers (both mandatory and well-formed):
  X-User-ID   : acting user identifier
  X-User-Role : one of {CampaignAdmin, Seller, Treasurer, SchoolOfficial}

Auth (priority 1): both headers present and well-formed else ERR_UNAUTHENTICATED (401).
RBAC (priority 2): role permitted for the operation else ERR_FORBIDDEN (403).

For role Seller, X-User-ID is the id of the acting Seller entity (ownership
checks compare a resource's seller_id FK to X-User-ID). For the other three
roles X-User-ID is an opaque operator identifier never matched to any entity.
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"CampaignAdmin", "Seller", "Treasurer", "SchoolOfficial"}


def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role == "" or role not in VALID_ROLES:
        raise errors.unauthenticated()
    if user_id is None or user_id.strip() == "":
        raise errors.unauthenticated()
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise errors.forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
