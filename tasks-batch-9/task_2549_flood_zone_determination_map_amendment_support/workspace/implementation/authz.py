"""Authentication and role authorisation (PRD section 2.1, ladder steps 1-3)."""
from flask import request

from errors import fail

ROLE_PROVIDER_ANALYST = "ProviderAnalyst"
ROLE_PROVIDER_REVIEWER = "ProviderReviewer"
ROLE_AGENCY_OFFICER = "AgencyOfficer"
ROLE_LENDER = "Lender"
ROLE_BORROWER = "Borrower"

ALL_ROLES = [
    ROLE_PROVIDER_ANALYST,
    ROLE_PROVIDER_REVIEWER,
    ROLE_AGENCY_OFFICER,
    ROLE_LENDER,
    ROLE_BORROWER,
]

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


class Actor(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_lender(self):
        return self.role == ROLE_LENDER

    @property
    def is_borrower(self):
        return self.role == ROLE_BORROWER


def authorize(allowed_roles):
    """Ladder step 1 and 2 (ERR_UNAUTHENTICATED) then step 3 (ERR_FORBIDDEN_ROLE)."""
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(USER_HEADER)

    if role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    role = role.strip()

    is_read = request.method == "GET"
    if not is_read and (user_id is None or user_id.strip() == ""):
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")

    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)

    if role not in allowed_roles:
        fail(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not authorised for this operation." % role,
        )

    return Actor(role, (user_id or "").strip() or None)
