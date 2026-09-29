"""Request admission: headers, roles, the entity-backed actor and pagination.

Ladder steps 1-3 and 5 of PRD 2.8.
"""
from flask import request

import db
import util
from errors import fail


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_brewer(self):
        return self.role == "Brewer"

    @property
    def is_distributor(self):
        return self.role == "Distributor"


def authenticate(*allowed_roles):
    """Steps 1-3: header presence and role validity, role authorisation, and
    for the entity-backed roles the existence of the acting row."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_UNAUTHENTICATED")
    if role not in util.ROLES:
        fail("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    if role == "Brewer" and user_id not in db.brewers:
        fail("ERR_UNKNOWN_ACTOR")
    if role == "Distributor" and user_id not in db.distributors:
        fail("ERR_UNKNOWN_ACTOR")
    return Actor(user_id, role)


def pagination():
    """Step 5: limit is an integer 1..100, offset an integer >= 0."""
    limit = _int_param("limit", 10)
    offset = _int_param("offset", 0)
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_PAGINATION")
    if offset < 0:
        fail("ERR_INVALID_PAGINATION")
    return limit, offset


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if text.startswith("+"):
        fail("ERR_INVALID_PAGINATION")
    body = text[1:] if text.startswith("-") else text
    if not body.isdigit():
        fail("ERR_INVALID_PAGINATION")
    return int(text)


def owner_check(actor, *candidate_ids):
    """Step 8: an entity-backed actor must own the named resource."""
    if actor.role not in ("Brewer", "Distributor"):
        return
    for candidate in candidate_ids:
        if candidate is not None and candidate == actor.user_id:
            return
    fail("ERR_NOT_RESOURCE_OWNER")


def qparam(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def qbool(name):
    raw = qparam(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be true or false." % name)
