"""Authentication, role membership and row-level scoping (PRD section 2.1).

Rejection order inside the auth tier (PRD section 2.7):
  ERR_UNAUTHENTICATED -> ERR_ROLE_NOT_PERMITTED -> ERR_ACTOR_NOT_ON_CASE
  -> ERR_REPRESENTATIVE_INACTIVE
"""

import functools

from flask import g, request

import store
from errors import ApiError

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

ROLES = (
    "ProgramDirector",
    "IntakeScreener",
    "SupervisingAttorney",
    "CaseRepresentative",
    "GrantAnalyst",
    "ClientPortalUser",
)

# Roles whose X-User-ID is a Representative.id
REP_ROLES = ("IntakeScreener", "SupervisingAttorney", "CaseRepresentative")

ASSIGNMENT_SCOPE_STATUSES = ("PROPOSED", "ACTIVE", "SUSPENDED")


def actor():
    return g.actor


def user_id():
    return g.actor["user_id"]


def role():
    return g.actor["role"]


def is_rep_backed():
    return g.actor["role"] in REP_ROLES


def acting_representative():
    """The Representative row backing the actor, when the role is rep-backed."""
    if not is_rep_backed():
        return None
    return store.get("representatives", g.actor["user_id"])


def _authenticate():
    uid = request.headers.get(USER_HEADER)
    rrole = request.headers.get(ROLE_HEADER)
    if uid is None or not str(uid).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing %s header." % USER_HEADER)
    if rrole is None or not str(rrole).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing %s header." % ROLE_HEADER)
    rrole = rrole.strip()
    if rrole not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'." % rrole)
    g.actor = {"user_id": str(uid).strip(), "role": rrole}


def check_rep_active():
    """ERR_REPRESENTATIVE_INACTIVE when the backing Representative is not ACTIVE."""
    rep = acting_representative()
    if rep is not None and rep.get("status") != "ACTIVE":
        raise ApiError(
            "ERR_REPRESENTATIVE_INACTIVE",
            "The acting representative is not ACTIVE.",
        )


def requires(*roles, **kwargs):
    """Route decorator: authenticate, then check endpoint role membership."""
    scoped = kwargs.get("scoped", False)
    allowed = set(roles)

    def decorate(view):
        @functools.wraps(view)
        def wrapper(*args, **kw):
            _authenticate()
            if g.actor["role"] not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role '%s' may not call this endpoint." % g.actor["role"],
                )
            if not scoped:
                check_rep_active()
            return view(*args, **kw)

        return wrapper

    return decorate


# --------------------------------------------------------------------------
# row-level scoping
# --------------------------------------------------------------------------

def _rep_holds_assignment(matter_id):
    for row in store.db["assignments"].values():
        if (row.get("matter_id") == matter_id
                and row.get("representative_id") == g.actor["user_id"]
                and row.get("status") in ASSIGNMENT_SCOPE_STATUSES):
            return True
    return False


def scope_matter(matter_id):
    """Row-level scoping for a matter-anchored operation, then rep-active check."""
    rrole = g.actor["role"]
    if rrole == "CaseRepresentative":
        if matter_id is None or not _rep_holds_assignment(matter_id):
            raise ApiError(
                "ERR_ACTOR_NOT_ON_CASE",
                "The acting representative holds no assignment on this matter.",
            )
    elif rrole == "ClientPortalUser":
        matter = store.get("matters", matter_id) if matter_id else None
        if matter is not None and matter.get("client_id") != g.actor["user_id"]:
            raise ApiError(
                "ERR_ACTOR_NOT_ON_CASE",
                "The acting client portal user may only act on its own rows.",
            )
    check_rep_active()


def scope_client(client_id):
    """Row-level scoping for a client-anchored operation, then rep-active check."""
    if g.actor["role"] == "ClientPortalUser":
        if client_id is not None and client_id != g.actor["user_id"]:
            raise ApiError(
                "ERR_ACTOR_NOT_ON_CASE",
                "The acting client portal user may only act on its own rows.",
            )
    check_rep_active()


def scope_none():
    check_rep_active()


def portal_client_id():
    """The client id a ClientPortalUser is restricted to, else None."""
    if g.actor["role"] == "ClientPortalUser":
        return g.actor["user_id"]
    return None
