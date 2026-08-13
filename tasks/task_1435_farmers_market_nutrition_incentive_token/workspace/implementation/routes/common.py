"""Shared route helpers: request pipeline pieces used by every endpoint."""

from flask import jsonify

from db import STORE, idem_marker
from errors import ApiError, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND
from middleware import (
    authenticate,
    get_body,
    idempotency_guard,
)


class Pipeline:
    """Carries per-request state: role/user, parsed body, idempotency key."""

    def __init__(self, allowed_roles, is_write):
        self.role, self.user_id = authenticate(allowed_roles)
        self.body = get_body()
        self.idem_key = None
        self.idem_fp = None
        if is_write:
            key, fp = idempotency_guard(self.body)
            self.idem_key = key
            self.idem_fp = fp

    def commit(self, status, envelope_body):
        if self.idem_key:
            idem_marker(self.idem_key, self.idem_fp, status, envelope_body)


def get_path_entity(table, entity_id):
    """Priority 5: path ids validated -> ERR_NOT_FOUND (404)."""
    entity = STORE[table].get(entity_id)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Resource {entity_id} does not exist")
    return entity


def ref_exists(table, value):
    """Priority 6: body-referenced FK must exist -> ERR_REFERENCE_NOT_FOUND.

    Only evaluated when the reference value is present and a string; missing
    or mistyped fields are left for the shape rung (priority 8).
    """
    if isinstance(value, str) and value not in STORE[table]:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422,
                       f"Referenced {table[:-1]} '{value}' does not exist")


def replay_response(replay):
    return jsonify(replay.body), replay.status
