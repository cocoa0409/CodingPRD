"""Authentication and role authorisation (PRD 2.1, ladder steps 1-2)."""
from flask import request as flask_request

from db import store
from errors import fail

ROLE_RECORDS_CLERK = "RecordsClerk"
ROLE_RECORDS_SUPERVISOR = "RecordsSupervisor"
ROLE_LEGAL_COUNSEL = "LegalCounsel"
ROLE_REDACTION_TECHNICIAN = "RedactionTechnician"
ROLE_QUALITY_REVIEWER = "QualityReviewer"
ROLE_REQUESTER = "Requester"

ALL_ROLES = (
    ROLE_RECORDS_CLERK,
    ROLE_RECORDS_SUPERVISOR,
    ROLE_LEGAL_COUNSEL,
    ROLE_REDACTION_TECHNICIAN,
    ROLE_QUALITY_REVIEWER,
    ROLE_REQUESTER,
)

# Roles whose X-User-ID must resolve to a persisted row.  RecordsClerk and
# RecordsSupervisor carry opaque operator identifiers instead.
ENTITY_BACKED_ROLES = {
    ROLE_LEGAL_COUNSEL: "staff",
    ROLE_REDACTION_TECHNICIAN: "staff",
    ROLE_QUALITY_REVIEWER: "staff",
    ROLE_REQUESTER: "requesters",
}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class Context(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.force_bump = set()
        self.mutating = False

    def touch(self, collection, row_id):
        """Force a version bump even when no stored field ended up changing."""
        if row_id:
            self.force_bump.add((collection, row_id))

    @property
    def staff(self):
        return store.get("staff", self.user_id)


def authenticate():
    user_id = flask_request.headers.get(HEADER_USER_ID)
    role = flask_request.headers.get(HEADER_USER_ROLE)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    user_id = str(user_id)
    role = str(role)
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "unknown role %r" % role)
    backing = ENTITY_BACKED_ROLES.get(role)
    if backing is not None and store.get(backing, user_id) is None:
        fail("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to a %s row" % backing)
    return Context(user_id, role)


def authorize(ctx, roles):
    if ctx.role not in roles:
        fail("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % ctx.role)
