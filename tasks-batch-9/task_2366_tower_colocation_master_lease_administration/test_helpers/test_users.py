"""Acting principals for the five roles of PRD §2.1.

Three roles are operator roles whose ``X-User-ID`` is opaque, so a fixed string
is enough. The remaining two are entity-backed: ``X-User-ID`` must be the ``id``
of an existing ``Tenant`` or ``Landlord`` row, so headers for those roles are
built per entity with :func:`make_tenant_headers` / :func:`make_landlord_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, build_user_headers

from .constants import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_LANDLORD,
    ROLE_PORTFOLIO_ADMIN,
    ROLE_STRUCTURAL_ENGINEER,
    ROLE_TENANT,
)

# ─── Opaque operator identifiers ─────────────────────────────────────────────

ADMIN_USER_ID = "admin-1"
ENGINEER_USER_ID = "eng-1"
OTHER_ENGINEER_USER_ID = "eng-2"
THIRD_ENGINEER_USER_ID = "eng-3"
AUDITOR_USER_ID = "aud-1"
OTHER_AUDITOR_USER_ID = "aud-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PORTFOLIO_ADMIN: {"user_id": ADMIN_USER_ID, "role": ROLE_PORTFOLIO_ADMIN},
    ROLE_STRUCTURAL_ENGINEER: {
        "user_id": ENGINEER_USER_ID,
        "role": ROLE_STRUCTURAL_ENGINEER,
    },
    ROLE_COMPLIANCE_AUDITOR: {"user_id": AUDITOR_USER_ID, "role": ROLE_COMPLIANCE_AUDITOR},
}

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PORTFOLIO_ADMIN)
ENGINEER_HEADERS = build_user_headers(ENGINEER_USER_ID, ROLE_STRUCTURAL_ENGINEER)
OTHER_ENGINEER_HEADERS = build_user_headers(
    OTHER_ENGINEER_USER_ID, ROLE_STRUCTURAL_ENGINEER
)
THIRD_ENGINEER_HEADERS = build_user_headers(
    THIRD_ENGINEER_USER_ID, ROLE_STRUCTURAL_ENGINEER
)
AUDITOR_HEADERS = build_user_headers(AUDITOR_USER_ID, ROLE_COMPLIANCE_AUDITOR)
OTHER_AUDITOR_HEADERS = build_user_headers(OTHER_AUDITOR_USER_ID, ROLE_COMPLIANCE_AUDITOR)


# ─── Entity-backed roles ─────────────────────────────────────────────────────


def make_tenant_headers(tenant_id: str) -> Dict[str, str]:
    """Headers for the ``Tenant`` role acting as the row whose ``id`` is given."""
    return build_user_headers(tenant_id, ROLE_TENANT)


def make_landlord_headers(landlord_id: str) -> Dict[str, str]:
    """Headers for the ``Landlord`` role acting as the row whose ``id`` is given."""
    return build_user_headers(landlord_id, ROLE_LANDLORD)


def make_engineer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named structural engineer operator identifier."""
    return build_user_headers(user_id, ROLE_STRUCTURAL_ENGINEER)


def make_auditor_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named compliance auditor operator identifier."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_AUDITOR)


# ─── Malformed / unresolvable principals ─────────────────────────────────────

UNRESOLVABLE_TENANT_HEADERS = make_tenant_headers(NON_EXISTENT_UUID)
UNRESOLVABLE_LANDLORD_HEADERS = make_landlord_headers(NON_EXISTENT_UUID)

MISSING_ROLE_HEADERS = {"X-User-ID": ADMIN_USER_ID, "Content-Type": "application/json"}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_PORTFOLIO_ADMIN,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers(ADMIN_USER_ID, "SiteTechnician")
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
