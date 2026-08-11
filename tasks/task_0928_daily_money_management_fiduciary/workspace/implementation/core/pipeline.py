"""The single ordered evaluation path of the PRD section 2.9 ladder.

Every handler walks the rungs in ascending numeric order, so precedence is
structural rather than incidental.  The helpers here implement the rungs that
are shared by every endpoint: 1 authentication, 2 role authorization,
3 existence, 4 request shape and 5 enum membership.
"""

from functools import wraps

from flask import g, request

from . import constants as K
from .audit import append_audit, audit_slot, set_subject, set_subject_entity
from .errors import ApiError, fail
from .store import db


class Ctx(object):
    __slots__ = ("role", "user_id", "body")

    def __init__(self, role, user_id, body):
        self.role = role
        self.user_id = user_id
        self.body = body

    # -- rung 4: request shape -------------------------------------------
    def check_shape(self, spec):
        """spec: iterable of (field_name, json_type, required) in input order."""
        for name, json_type, required in spec:
            if name not in self.body or self.body.get(name) is None:
                if required:
                    fail("ERR_VALIDATION", "Field '{}' is required.".format(name))
                continue
            value = self.body[name]
            if not _typed(value, json_type):
                fail(
                    "ERR_VALIDATION",
                    "Field '{}' must be of type {}.".format(name, json_type),
                )

    def require_conditional(self, name, json_type=str):
        """A field the selected action makes required (PRD 2.9 rung 4)."""
        if name not in self.body or self.body.get(name) is None:
            fail("ERR_VALIDATION", "Field '{}' is required for this action.".format(name))
        if not _typed(self.body[name], json_type):
            fail("ERR_VALIDATION", "Field '{}' must be of type {}.".format(name, json_type))

    # -- rung 5: enum membership -----------------------------------------
    def check_enum(self, name, members):
        value = self.body.get(name)
        if value is None:
            return
        if value not in members:
            fail("ERR_INVALID_ENUM", "Field '{}' is not a declared member.".format(name))

    def check_enum_list(self, name, members):
        value = self.body.get(name)
        if not isinstance(value, list):
            return
        for element in value:
            if element not in members:
                fail(
                    "ERR_INVALID_ENUM",
                    "Element of '{}' is not a declared member.".format(name),
                )

    def get(self, name, default=None):
        value = self.body.get(name)
        return default if value is None else value


def _typed(value, json_type):
    if json_type is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type is bool:
        return isinstance(value, bool)
    if json_type is str:
        return isinstance(value, str)
    if json_type is list:
        return isinstance(value, list)
    if json_type is dict:
        return isinstance(value, dict)
    return True


def _body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def authorize(*allowed_roles):
    """Rung 1 (authentication) then rung 2 (role authorization)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in K.ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unknown caller identity.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role {} may not call this endpoint.".format(role))
    return Ctx(role, user_id, _body())


# -- rung 3: existence ----------------------------------------------------

def resolve_client(client_id):
    row = db.clients.get(client_id) if isinstance(client_id, str) else None
    if row is None:
        fail("ERR_CLIENT_NOT_FOUND", "No such client.")
    return row


def resolve(collection, row_id):
    row = getattr(db, collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "No such resource.")
    return row


def resolve_body_client(ctx, field="client_id"):
    value = ctx.body.get(field)
    if not isinstance(value, str):
        return None
    return resolve_client(value)


def resolve_body_ref(ctx, field, collection):
    value = ctx.body.get(field)
    if not isinstance(value, str):
        return None
    return resolve(collection, value)


# -- the audit wrapper ----------------------------------------------------

def audited(subject_entity, path_param=None):
    """Wrap a POST view so exactly one AuditEntry is appended either way."""

    def decorator(view):
        @wraps(view)
        def wrapper(**kwargs):
            slot = audit_slot()
            set_subject_entity(subject_entity)
            if path_param is not None:
                set_subject(kwargs.get(path_param))
            try:
                result = view(**kwargs)
            except ApiError as exc:
                append_audit("REJECTED", exc.error_id)
                raise
            append_audit("SUCCESS", None)
            return result

        return wrapper

    return decorator
