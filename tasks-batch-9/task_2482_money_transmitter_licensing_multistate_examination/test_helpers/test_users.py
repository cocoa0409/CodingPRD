"""Acting identities and the header dictionaries that carry them.

PRD 2.1 splits the six roles in two. ``PlatformAdmin``, ``LicensingManager``,
``ComplianceOfficer`` and ``ChiefComplianceOfficer`` carry an opaque operator
identifier that the server never compares to any entity id, so those identities
are fixed constants here. ``StateRegulator`` and ``DelegateOperator`` are
entity-backed: their ``X-User-ID`` must be the id of the acting ``Jurisdiction``
or ``Delegate`` respectively, so their headers are built per test from a live id.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CHIEF_COMPLIANCE_OFFICER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DELEGATE_OPERATOR,
    ROLE_LICENSING_MANAGER,
    ROLE_PLATFORM_ADMIN,
    ROLE_STATE_REGULATOR,
)

# ---------------------------------------------------------------------------
# Opaque operator identities (PRD 2.1)
# ---------------------------------------------------------------------------

USER_PLATFORM_ADMIN = "u_admin_root"
USER_LICENSING_MANAGER = "u_lm_avery"
USER_SECOND_LICENSING_MANAGER = "u_lm_blake"
USER_COMPLIANCE_OFFICER = "u_co_cameron"
USER_SECOND_COMPLIANCE_OFFICER = "u_co_devon"
USER_CHIEF_COMPLIANCE_OFFICER = "u_cco_dana"
USER_SECOND_CHIEF_COMPLIANCE_OFFICER = "u_cco_ellis"

TEST_USERS: Dict[str, str] = {
    ROLE_PLATFORM_ADMIN: USER_PLATFORM_ADMIN,
    ROLE_LICENSING_MANAGER: USER_LICENSING_MANAGER,
    ROLE_COMPLIANCE_OFFICER: USER_COMPLIANCE_OFFICER,
    ROLE_CHIEF_COMPLIANCE_OFFICER: USER_CHIEF_COMPLIANCE_OFFICER,
}

ADMIN_HEADERS = build_user_headers(USER_PLATFORM_ADMIN, ROLE_PLATFORM_ADMIN)
MANAGER_HEADERS = build_user_headers(USER_LICENSING_MANAGER, ROLE_LICENSING_MANAGER)
SECOND_MANAGER_HEADERS = build_user_headers(
    USER_SECOND_LICENSING_MANAGER, ROLE_LICENSING_MANAGER
)
OFFICER_HEADERS = build_user_headers(USER_COMPLIANCE_OFFICER, ROLE_COMPLIANCE_OFFICER)
SECOND_OFFICER_HEADERS = build_user_headers(
    USER_SECOND_COMPLIANCE_OFFICER, ROLE_COMPLIANCE_OFFICER
)
CHIEF_HEADERS = build_user_headers(
    USER_CHIEF_COMPLIANCE_OFFICER, ROLE_CHIEF_COMPLIANCE_OFFICER
)
SECOND_CHIEF_HEADERS = build_user_headers(
    USER_SECOND_CHIEF_COMPLIANCE_OFFICER, ROLE_CHIEF_COMPLIANCE_OFFICER
)


# ---------------------------------------------------------------------------
# Entity-backed identities (PRD 2.1)
# ---------------------------------------------------------------------------


def make_state_regulator_headers(jurisdiction_id: str) -> Dict[str, str]:
    """Headers for the regulator of one jurisdiction: X-User-ID is its id."""
    return build_user_headers(jurisdiction_id, ROLE_STATE_REGULATOR)


def make_delegate_operator_headers(delegate_id: str) -> Dict[str, str]:
    """Headers for an agent's own operator: X-User-ID is the delegate's id."""
    return build_user_headers(delegate_id, ROLE_DELEGATE_OPERATOR)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identity and role pair."""
    return build_user_headers(user_id, role)


def make_headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that declare a role but omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that identify a principal but omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_for_role(role: str, entity_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for any of the six roles, threading an id for the backed two."""
    if role in (ROLE_STATE_REGULATOR, ROLE_DELEGATE_OPERATOR):
        if entity_id is None:
            raise ValueError(f"{role} requires the id of the acting entity")
        return build_user_headers(entity_id, role)
    return build_user_headers(TEST_USERS[role], role)
