"""Acting identities and header builders.

Every request carries ``X-User-ID`` and ``X-User-Role`` (PRD §2.1).  Four of the
five roles are opaque operator identifiers, so a fixed catalogue of ids is
enough.  ``TenantRep`` is entity-backed: its ``X-User-ID`` must be the ``id`` of
a real ``Tenant`` row, so its builder takes the tenant id as an argument and
tests must thread the tenant they actually created.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque operator identities
# --------------------------------------------------------------------------
LEASE_ADMIN_USER_ID = "la-admin-1"
LEASE_ADMIN_ALT_USER_ID = "la-admin-2"

COMPLIANCE_OFFICER_USER_ID = "co-analyst-1"
COMPLIANCE_ENFORCER_USER_ID = "co-enforce-1"
COMPLIANCE_REVIEWER_USER_ID = "co-reviewer-2"
COMPLIANCE_ADJUDICATOR_USER_ID = "co-adjudicator-2"
COMPLIANCE_SWEEPER_USER_ID = "co-sweeper-3"

ASSET_MANAGER_USER_ID = "am-portfolio-1"
ASSET_MANAGER_ALT_USER_ID = "pm-1"

LENDER_REP_USER_ID = "lender-agent-1"
LENDER_REP_ALT_USER_ID = "lender-agent-2"


# Shared catalogue of every non-entity-backed identity, keyed by a short label.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "lease_admin": {
        "user_id": LEASE_ADMIN_USER_ID,
        "role": UserRole.LEASE_ADMINISTRATOR.value,
    },
    "lease_admin_alt": {
        "user_id": LEASE_ADMIN_ALT_USER_ID,
        "role": UserRole.LEASE_ADMINISTRATOR.value,
    },
    "compliance_officer": {
        "user_id": COMPLIANCE_OFFICER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "compliance_enforcer": {
        "user_id": COMPLIANCE_ENFORCER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "compliance_reviewer": {
        "user_id": COMPLIANCE_REVIEWER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "compliance_adjudicator": {
        "user_id": COMPLIANCE_ADJUDICATOR_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "compliance_sweeper": {
        "user_id": COMPLIANCE_SWEEPER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "asset_manager": {
        "user_id": ASSET_MANAGER_USER_ID,
        "role": UserRole.ASSET_MANAGER.value,
    },
    "asset_manager_alt": {
        "user_id": ASSET_MANAGER_ALT_USER_ID,
        "role": UserRole.ASSET_MANAGER.value,
    },
    "lender_rep": {
        "user_id": LENDER_REP_USER_ID,
        "role": UserRole.LENDER_REP.value,
    },
    "lender_rep_alt": {
        "user_id": LENDER_REP_ALT_USER_ID,
        "role": UserRole.LENDER_REP.value,
    },
}


# --------------------------------------------------------------------------
# Per-role header builders
# --------------------------------------------------------------------------
def make_lease_administrator_headers(
    user_id: str = LEASE_ADMIN_USER_ID,
) -> Dict[str, str]:
    """Headers for a ``LeaseAdministrator`` acting as ``user_id``."""
    return build_user_headers(user_id, UserRole.LEASE_ADMINISTRATOR.value)


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> Dict[str, str]:
    """Headers for a ``ComplianceOfficer`` acting as ``user_id``.

    The officer identity matters: the officer who issued a notice may not
    adjudicate its dispute, and the officer who prepared a measurement may not
    certify it (PRD §2.1).
    """
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_asset_manager_headers(
    user_id: str = ASSET_MANAGER_USER_ID,
) -> Dict[str, str]:
    """Headers for an ``AssetManager`` acting as ``user_id``."""
    return build_user_headers(user_id, UserRole.ASSET_MANAGER.value)


def make_tenant_rep_headers(tenant_id: str) -> Dict[str, str]:
    """Headers for a ``TenantRep`` whose ``X-User-ID`` is a ``Tenant`` id.

    ``tenant_id`` must be the id of a tenant that exists, because ownership
    checks compare the addressed resource's ``tenant_id`` to this header.
    """
    return build_user_headers(tenant_id, UserRole.TENANT_REP.value)


def make_lender_rep_headers(user_id: str = LENDER_REP_USER_ID) -> Dict[str, str]:
    """Headers for a ``LenderRep`` acting as ``user_id``."""
    return build_user_headers(user_id, UserRole.LENDER_REP.value)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder for an arbitrary role/id pair."""
    return build_user_headers(user_id, role)


def make_headers_missing_role(user_id: str = LEASE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers that omit ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_blank_role(user_id: str = LEASE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is blank."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def make_headers_unknown_role(
    user_id: str = LEASE_ADMIN_USER_ID, role: str = "PropertyAccountant"
) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is not one of the five recognized names."""
    return build_user_headers(user_id, role)


# Convenience aliases matching the shorter names used across the suite.
make_lease_admin_headers = make_lease_administrator_headers
LEASE_ADMIN_HEADERS = make_lease_administrator_headers()
COMPLIANCE_OFFICER_HEADERS = make_compliance_officer_headers()
ASSET_MANAGER_HEADERS = make_asset_manager_headers()
LENDER_REP_HEADERS = make_lender_rep_headers()
