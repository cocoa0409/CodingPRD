"""Authentication, role authorisation and entity-backed scope (PRD 2.1)."""
import functools

from flask import g, request

from errors import fail
from store import db

PLACEMENT_COORDINATOR = "PlacementCoordinator"
TEAM_CHAIR = "TeamChair"
FISCAL_OFFICER = "FiscalOfficer"
SCHOOL_BILLING_AGENT = "SchoolBillingAgent"
PARENT_GUARDIAN = "ParentGuardian"
HEARING_ADJUDICATOR = "HearingAdjudicator"
SYSTEM_ADMIN = "SystemAdmin"

ROLES = (
    PLACEMENT_COORDINATOR,
    TEAM_CHAIR,
    FISCAL_OFFICER,
    SCHOOL_BILLING_AGENT,
    PARENT_GUARDIAN,
    HEARING_ADJUDICATOR,
    SYSTEM_ADMIN,
)

ALL_ROLES = ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def authorize(roles):
    if g.role not in roles:
        fail("ERR_ROLE_NOT_PERMITTED")


def endpoint(bp, method, rule, roles):
    """Register a handler, wiring rungs 1 and 2 of the refusal ladder."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            authenticate()
            authorize(roles)
            return fn(**kwargs)

        bp.add_url_rule(rule, endpoint=fn.__name__, view_func=wrapper, methods=[method])
        return fn

    return decorator


# --------------------------------------------------------------------------
# entity-backed scope resolution (rung 6)
# --------------------------------------------------------------------------

_VIA_PLACEMENT = (
    "addendum",
    "assignment",
    "attendance",
    "invoice",
    "progress",
    "plan",
    "funding",
)


def _placement_of(row):
    return db.placements.get(row.get("placement_id"))


def school_of(row):
    kind = row.get("_kind")
    if kind == "school":
        return row["id"]
    if kind == "rate_schedule":
        return row.get("school_id")
    if kind == "placement":
        return row.get("school_id")
    if kind in _VIA_PLACEMENT:
        parent = _placement_of(row)
        return parent.get("school_id") if parent else None
    return None


def student_of(row):
    kind = row.get("_kind")
    if kind == "student":
        return row["id"]
    if kind in ("decision", "placement", "reimbursement"):
        return row.get("student_id")
    if kind in _VIA_PLACEMENT:
        parent = _placement_of(row)
        return parent.get("student_id") if parent else None
    return None


def in_scope(row):
    role = g.get("role", None)
    if role == SCHOOL_BILLING_AGENT:
        owner = school_of(row)
        return owner is None or owner == g.user_id
    if role == PARENT_GUARDIAN:
        owner = student_of(row)
        return owner is None or owner == g.user_id
    return True


def check_scope(row):
    if not in_scope(row):
        fail("ERR_OUT_OF_SCOPE")


def scope_filter(rows):
    role = g.get("role", None)
    if role not in (SCHOOL_BILLING_AGENT, PARENT_GUARDIAN):
        return rows
    return [r for r in rows if in_scope(r)]
