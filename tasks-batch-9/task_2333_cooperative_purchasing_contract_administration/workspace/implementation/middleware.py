"""Auth header handling (PRD 2.1), role gating and mutation bookkeeping."""

from functools import wraps

from flask import g, request

from db import logical_now_iso
from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_COOP_ADMIN = "CoopAdministrator"
ROLE_LEAD_AGENCY = "LeadAgencyOfficer"
ROLE_SUPPLIER = "SupplierRepresentative"
ROLE_MEMBER = "MemberRepresentative"
ROLE_AUDITOR = "MemberAuditor"

KNOWN_ROLES = (
    ROLE_COOP_ADMIN,
    ROLE_LEAD_AGENCY,
    ROLE_SUPPLIER,
    ROLE_MEMBER,
    ROLE_AUDITOR,
)


def begin_request():
    g.dirty = {}
    g.fresh = set()
    g.actor_id = None
    g.actor_role = None


def _authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None:
        fail("ERR_MISSING_AUTH_HEADERS")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail("ERR_MISSING_AUTH_HEADERS")
    if role not in KNOWN_ROLES:
        fail("ERR_MISSING_AUTH_HEADERS")
    g.actor_id = user_id
    g.actor_role = role
    return user_id, role


def require_roles(*roles):
    """Ladder steps 1 and 2: authentication, then endpoint role membership."""

    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _, role = _authenticate()
            if role not in allowed:
                fail("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.actor_id


def actor_role():
    return g.actor_role


# --------------------------------------------------------------------------
# mutation bookkeeping: exactly one version bump per touched row per request
# --------------------------------------------------------------------------

def register_new(row):
    """A row created by this request keeps version 1 and is never bumped."""
    g.fresh.add(id(row))


def touch(row):
    """Mark a pre-existing mutable row as changed by this request."""
    if row is None:
        return
    if "version" not in row:
        return  # immutable entity (StateLawRule)
    if id(row) in g.fresh:
        return
    g.dirty[id(row)] = row


def commit():
    """Apply updated_at / version to every row touched during this request."""
    stamp = logical_now_iso()
    for row in list(g.dirty.values()):
        row["version"] = int(row.get("version", 1)) + 1
        row["updated_at"] = stamp
    g.dirty = {}
