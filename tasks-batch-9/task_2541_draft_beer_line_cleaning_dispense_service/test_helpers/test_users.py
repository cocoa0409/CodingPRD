"""Pre-built authentication headers for every role the PRD defines.

Two roles are identity-bearing: a `ServiceTechnician` presents the identifier of
its own technician row and a `VenueManager` presents the identifier of its own
service account.  Those two must therefore be built per entity with the
``make_*`` helpers below; the opaque roles can reuse the shared constants.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- Opaque identities ------------------------------------------------------
DISPATCH_USER_ID = "dispatch-1"
AUDITOR_USER_ID = "auditor-1"
SECOND_AUDITOR_USER_ID = "auditor-2"
BREWER_USER_ID = "brewer-1"

DISPATCH_HEADERS = build_user_headers(DISPATCH_USER_ID, Role.DISPATCH_COORDINATOR)
AUDITOR_HEADERS = build_user_headers(AUDITOR_USER_ID, Role.QUALITY_AUDITOR)
SECOND_AUDITOR_HEADERS = build_user_headers(SECOND_AUDITOR_USER_ID, Role.QUALITY_AUDITOR)
BREWER_HEADERS = build_user_headers(BREWER_USER_ID, Role.BREWER_REP)


# --- Identity-bearing roles -------------------------------------------------
def make_service_technician_headers(technician_id: str) -> Dict[str, str]:
    """Headers for the technician whose own row identifier is ``technician_id``."""
    return build_user_headers(technician_id, Role.SERVICE_TECHNICIAN)


def make_venue_manager_headers(account_id: str) -> Dict[str, str]:
    """Headers for the venue manager of the account ``account_id``."""
    return build_user_headers(account_id, Role.VENUE_MANAGER)


def make_quality_auditor_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named auditor, for rules that compare two auditor identities."""
    return build_user_headers(user_id, Role.QUALITY_AUDITOR)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but no user identifier."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying a user identifier but no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


#: Role headers a pytest fixture can hand straight to a test.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "dispatch_headers": DISPATCH_HEADERS,
    "auditor_headers": AUDITOR_HEADERS,
    "second_auditor_headers": SECOND_AUDITOR_HEADERS,
    "brewer_headers": BREWER_HEADERS,
}
