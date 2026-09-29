"""Authentication, endpoint/action authorization and client scoping."""

from flask import request

from envelope import parse_body
from errors import (
    ApiError,
    ERR_CLIENT_SCOPE_VIOLATION,
    ERR_FORBIDDEN_ROLE,
    ERR_UNAUTHENTICATED,
)

FACILITY_ADMIN = "FacilityAdmin"
CELLAR_SUPERVISOR = "CellarSupervisor"
COMPLIANCE_OFFICER = "ComplianceOfficer"
CLIENT_REP = "ClientRep"

ALL_ROLES = [FACILITY_ADMIN, CELLAR_SUPERVISOR, COMPLIANCE_OFFICER, CLIENT_REP]
KNOWN_ROLES = set(ALL_ROLES)


class Ctx:
    __slots__ = ("user_id", "role", "_body", "_parse_error")

    def __init__(self, user_id, role, body, parse_error):
        self.user_id = user_id
        self.role = role
        self._body = body
        self._parse_error = parse_error

    @property
    def body(self):
        """Rung 5: a malformed body surfaces here, after role authorization."""
        if self._parse_error is not None:
            raise self._parse_error
        return self._body if self._body is not None else {}

    @property
    def raw_body(self):
        return self._body if self._body is not None else {}

    @property
    def is_client_rep(self):
        return self.role == CLIENT_REP


def guard(roles, action_actors=None, read_body=True):
    """Ladder rungs 1-3."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()

    # Rung 1 -- both headers present and non-empty.
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "Both X-User-ID and X-User-Role are required.")
    # Rung 2 -- the role must be one of the four the facility recognises.
    if role not in KNOWN_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Unknown role '%s'." % role)

    body, parse_error = ({}, None)
    if read_body:
        body, parse_error = parse_body()

    # Rung 3 -- endpoint authorization.
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN_ROLE,
                       "Role '%s' is not authorized for this endpoint." % role)

    # Rung 3 -- per-action actor authorization on multiplexing endpoints.
    if action_actors and body is not None:
        action = body.get("action")
        if isinstance(action, str) and action in action_actors:
            allowed = action_actors[action]
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_ROLE,
                    "Role '%s' may not send action '%s'." % (role, action))

    return Ctx(user_id, role, body, parse_error)


def scope(ctx, owner_client_id):
    """Ladder rung 20 -- a ClientRep may only touch its own client's estate."""
    if ctx.role == CLIENT_REP and ctx.user_id != owner_client_id:
        raise ApiError(ERR_CLIENT_SCOPE_VIOLATION,
                       "This resource does not belong to the acting client.")


def forbid_action_actor(ctx, expected_actor):
    """State-dependent actor mismatch (only WorkOrder COMPLETE needs this)."""
    if ctx.role != expected_actor:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Role '%s' may not perform this action from the current state." % ctx.role)
