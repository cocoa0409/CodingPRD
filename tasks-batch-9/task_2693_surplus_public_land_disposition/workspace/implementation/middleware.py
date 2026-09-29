"""Authentication, role permission and entity-backed identity resolution
(PRD 2.1, and the first four rungs of the precedence order in PRD 2.10).
"""

from functools import wraps

from flask import g, request

import db
from errors import fail

RPO = "RealPropertyOfficer"
CLERK = "BoardClerk"
MONITOR = "ComplianceMonitor"
FINANCE = "FinanceOfficer"
AGENCY_REP = "AgencyRepresentative"
APPRAISER = "Appraiser"
BIDDER = "Bidder"
SYSADMIN = "SystemAdministrator"

ALL_ROLES = (RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, APPRAISER, BIDDER, SYSADMIN)

ENTITY_BACKED = {
    AGENCY_REP: "agencies",
    APPRAISER: "appraisers",
    BIDDER: "bidders",
}


def authorize(*roles):
    allowed = set(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if role is None or role == "" or role not in ALL_ROLES:
                fail("ERR_UNAUTHENTICATED", "X-User-Role must name one of the declared roles.")
            user_id = request.headers.get("X-User-ID")
            if user_id is None or user_id == "":
                fail("ERR_UNAUTHENTICATED", "X-User-ID is required.")
            if role not in allowed:
                fail("ERR_UNAUTHORIZED", "Role %s may not use this endpoint." % role)
            g.role = role
            g.user_id = user_id
            g.actor = None
            collection = ENTITY_BACKED.get(role)
            if collection is not None:
                actor = db.get(collection, user_id)
                if actor is None:
                    fail("ERR_IDENTITY_NOT_RESOLVABLE",
                         "X-User-ID does not resolve to a %s row." % collection[:-1])
                g.actor = actor
            return view(*args, **kwargs)

        return wrapper

    return decorator
