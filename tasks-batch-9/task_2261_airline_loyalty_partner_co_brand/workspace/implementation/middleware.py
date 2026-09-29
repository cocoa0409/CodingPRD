"""Auth header extraction, RBAC and the shared request-shape helpers.

PRD 2.1: every request carries X-User-ID and X-User-Role; X-User-Role must be
exactly one of the seven declared role names.
"""

from flask import request

from errors import fail

ROLES = (
    "ProgramAdmin",
    "PartnerManager",
    "ContractsOfficer",
    "RevenueAccountant",
    "FraudAnalyst",
    "IssuerRepresentative",
    "Member",
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == "Member"

    @property
    def is_issuer_rep(self):
        return self.role == "IssuerRepresentative"


def authenticate(allowed_roles):
    """Ladder rungs 1 and 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role are required")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "role %s may not perform this operation" % role)
    return Caller(user_id, role)


def body():
    """Request JSON body as a dict; a missing or empty body becomes {}."""
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return raw


def page_params():
    """PRD 2.3 -- limit defaults to 10 (min 1, max 100), offset defaults to 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    offset = 0
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0")

    return limit, offset


def qfilter(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
