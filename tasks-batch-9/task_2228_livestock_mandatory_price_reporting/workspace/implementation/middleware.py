"""Authentication and role-based authorization (PRD §2.1).

Every request carries X-User-ID and X-User-Role. Authentication (401) is checked
before authorization (403), and both before request shape, path resolution and
every business rule.
"""

import functools

from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLE_REPORTER_AGENT = "ReporterAgent"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_MARKET_ANALYST = "MarketAnalyst"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"
ROLE_PENALTY_OFFICER = "PenaltyOfficer"
ROLE_PUBLIC_USER = "PublicUser"

ALL_ROLES = (
    ROLE_REPORTER_AGENT,
    ROLE_PROGRAM_ADMIN,
    ROLE_MARKET_ANALYST,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_PUBLIC_USER,
)


def authenticate():
    """Populate g.user_id / g.role or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    g.user_id = user_id
    g.role = role


def roles(*allowed):
    """Endpoint role gate; the presented role must appear in the endpoint's list."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if g.get("role") not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED,
                    "Role %s is not authorized for this operation." % g.get("role"),
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_role():
    return g.get("role")


def current_user_id():
    return g.get("user_id")


def is_reporter_agent():
    return g.get("role") == ROLE_REPORTER_AGENT


def is_public_user():
    return g.get("role") == ROLE_PUBLIC_USER
