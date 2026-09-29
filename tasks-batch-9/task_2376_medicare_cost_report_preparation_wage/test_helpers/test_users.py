"""Role headers for the five roles the PRD names (PRD 2.1).

Two roles are provider-scoped: when a ReimbursementAnalyst or a
ReimbursementManager sends an identifying header naming a provider, the request
must stay inside that provider's data.  When the header is absent the scope
check does not fire at all, so the shared constants below carry only the role
header and are safe on any endpoint the role owns.  Call the
``make_*_headers(provider_id)`` builders whenever a test needs the scope check
to actually engage.
"""

from .types import UserRole

_JSON = "application/json"


def _role_headers(role):
    return {"X-User-Role": str(role), "Content-Type": _JSON}


def _identified_headers(role, user_id):
    return {
        "X-User-Role": str(role),
        "X-User-ID": str(user_id),
        "Content-Type": _JSON,
    }


# ---------------------------------------------------------------------------
# Shared, unscoped role headers
# ---------------------------------------------------------------------------

TEST_USERS = {
    "system_admin": _role_headers(UserRole.SYSTEM_ADMIN.value),
    "reimbursement_analyst": _role_headers(UserRole.REIMBURSEMENT_ANALYST.value),
    "reimbursement_manager": _role_headers(UserRole.REIMBURSEMENT_MANAGER.value),
    "mac_auditor": _role_headers(UserRole.MAC_AUDITOR.value),
    "review_board_clerk": _role_headers(UserRole.REVIEW_BOARD_CLERK.value),
}

SYSTEM_ADMIN_HEADERS = TEST_USERS["system_admin"]
ANALYST_HEADERS = TEST_USERS["reimbursement_analyst"]
MANAGER_HEADERS = TEST_USERS["reimbursement_manager"]
AUDITOR_HEADERS = TEST_USERS["mac_auditor"]
CLERK_HEADERS = TEST_USERS["review_board_clerk"]

# Opaque auditor identities.  The audit endpoints compare the proposing and the
# resolving user, so two distinct auditors are needed.
AUDITOR_ONE_ID = "mac-auditor-1"
AUDITOR_TWO_ID = "mac-auditor-2"


# ---------------------------------------------------------------------------
# Identity-threading builders
# ---------------------------------------------------------------------------


def make_system_admin_headers(user_id="admin-001"):
    return _identified_headers(UserRole.SYSTEM_ADMIN.value, user_id)


def make_reimbursement_analyst_headers(provider_id):
    """Analyst headers scoped to ``provider_id``."""
    return _identified_headers(UserRole.REIMBURSEMENT_ANALYST.value, provider_id)


def make_reimbursement_manager_headers(provider_id):
    """Manager headers scoped to ``provider_id``."""
    return _identified_headers(UserRole.REIMBURSEMENT_MANAGER.value, provider_id)


def make_mac_auditor_headers(user_id=AUDITOR_ONE_ID):
    return _identified_headers(UserRole.MAC_AUDITOR.value, user_id)


def make_review_board_clerk_headers(user_id="clerk-001"):
    return _identified_headers(UserRole.REVIEW_BOARD_CLERK.value, user_id)


def no_auth_headers():
    """Headers with no role at all, for the unauthenticated path."""
    return {"Content-Type": _JSON}
