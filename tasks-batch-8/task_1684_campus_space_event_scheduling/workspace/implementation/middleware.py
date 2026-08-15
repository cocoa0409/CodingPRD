"""Endpoint registry and the auth rungs of the PRD 2.9 validation ladder.

Rung 1 (ERR_UNAUTHENTICATED) and rung 2 (ERR_FORBIDDEN) are evaluated here,
before any handler logic; every later rung is evaluated inside handlers in the
pinned order.
"""

import re

from constants import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import ApiError

ENDPOINTS = []

_PARAM_RE = re.compile(r"\{([a-z_]+)\}")


class Spec(object):
    def __init__(self, method, template, roles, code, handler):
        self.method = method
        self.template = template
        self.roles = tuple(roles)
        self.code = code
        self.handler = handler
        self.params = _PARAM_RE.findall(template)
        self.flask_rule = _PARAM_RE.sub(lambda m: "<" + m.group(1) + ">", template)
        self.name = handler.__name__


def endpoint(method, template, roles, code=200):
    def decorator(fn):
        ENDPOINTS.append(Spec(method, template, roles, code, fn))
        return fn

    return decorator


class Ctx(object):
    """Everything a handler needs about the request in flight."""

    __slots__ = ("spec", "role", "user_id", "body", "args", "path")

    def __init__(self, spec, role, user_id, body, args, path):
        self.spec = spec
        self.role = role
        self.user_id = user_id
        self.body = body
        self.args = args
        self.path = path

    @property
    def id(self):
        return self.path.get("id")

    @property
    def is_org_requester(self):
        return self.role == "OrgRequester"


def authenticate(role, user_id):
    """Rung 1: headers present and role recognized."""
    if not role or not user_id or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")


def authorize(spec, role):
    """Rung 2: the role is permitted for this endpoint."""
    if role not in spec.roles:
        raise ApiError("ERR_FORBIDDEN")
