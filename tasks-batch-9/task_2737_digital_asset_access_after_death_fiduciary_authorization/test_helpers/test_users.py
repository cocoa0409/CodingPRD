"""
Caller identities for the four roles the contract recognises.

Two of the four roles are backed by a stored entity, so their ``X-User-ID`` has
to be a real identifier created during setup:

  * ``Fiduciary``          — ``X-User-ID`` must be the id of a Fiduciary of the
    estate the call touches, otherwise the call is refused as a cross-estate
    access attempt.
  * ``PlatformCompliance`` — ``X-User-ID`` must be the id of the Platform the
    resource under the call belongs to, otherwise the call is refused as an
    out-of-scope provider.

The remaining two roles are opaque: any stable identifier works, so the module
exposes them as shared constants.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COURT_REGISTRAR,
    ROLE_ESTATE_ADMIN,
    ROLE_FIDUCIARY,
    ROLE_PLATFORM_COMPLIANCE,
)

# ─── Opaque-identity roles: fixed identifiers reused by every test ───────────
COURT_REGISTRAR_USER_ID = "11111111-1111-4111-8111-111111111111"
ESTATE_ADMIN_USER_ID = "22222222-2222-4222-8222-222222222222"

COURT_REGISTRAR_HEADERS: Dict[str, str] = build_user_headers(
    COURT_REGISTRAR_USER_ID, ROLE_COURT_REGISTRAR
)
ESTATE_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    ESTATE_ADMIN_USER_ID, ROLE_ESTATE_ADMIN
)

# A second registrar / admin identity, for tests that need to tell two callers
# of the same role apart.
OTHER_COURT_REGISTRAR_USER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_COURT_REGISTRAR_HEADERS: Dict[str, str] = build_user_headers(
    OTHER_COURT_REGISTRAR_USER_ID, ROLE_COURT_REGISTRAR
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_COURT_REGISTRAR: COURT_REGISTRAR_HEADERS,
    ROLE_ESTATE_ADMIN: ESTATE_ADMIN_HEADERS,
}


# ─── Entity-backed roles: per-instance header builders ───────────────────────
def make_fiduciary_headers(fiduciary_id: str) -> Dict[str, str]:
    """Headers for the Fiduciary role, identified by a stored Fiduciary id."""
    return build_user_headers(fiduciary_id, ROLE_FIDUCIARY)


def make_platform_compliance_headers(platform_id: str) -> Dict[str, str]:
    """Headers for the PlatformCompliance role, identified by a Platform id."""
    return build_user_headers(platform_id, ROLE_PLATFORM_COMPLIANCE)


def make_court_registrar_headers(user_id: str = COURT_REGISTRAR_USER_ID) -> Dict[str, str]:
    """Headers for the CourtRegistrar role; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_COURT_REGISTRAR)


def make_estate_admin_headers(user_id: str = ESTATE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for the EstateAdmin role; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_ESTATE_ADMIN)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary (role, user_id) pair — useful for role sweeps."""
    return build_user_headers(user_id, role)


# ─── Malformed identities, for the authentication band ──────────────────────
def make_unknown_role_headers(user_id: str = ESTATE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers carrying a role name the contract does not define."""
    return build_user_headers(user_id, "Notary")


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": ROLE_ESTATE_ADMIN,
    "Content-Type": "application/json",
}

MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": ESTATE_ADMIN_USER_ID,
    "Content-Type": "application/json",
}
