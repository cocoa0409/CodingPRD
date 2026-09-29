"""Identity header builders for the four declared roles.

`NetworkAdmin` and `VerificationAnalyst` carry opaque principal identifiers.
A `ContractorAdmin` must present the acting Contractor's `id` and a
`ClientSafetyManager` must present the acting Client's `id`, so those two
builders take the entity identifier they act for.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ANALYST_INSURANCE,
    ANALYST_STATISTICS,
    NETWORK_ADMIN_USER,
    ROLE_CLIENT_SAFETY_MANAGER,
    ROLE_CONTRACTOR_ADMIN,
    ROLE_NETWORK_ADMIN,
    ROLE_VERIFICATION_ANALYST,
)


def make_network_admin_headers(user_id: str = NETWORK_ADMIN_USER) -> dict:
    """Headers for the network operator; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_NETWORK_ADMIN)


def make_contractor_admin_headers(contractor_id: str) -> dict:
    """Headers for the admin of one contractor; X-User-ID is the Contractor id."""
    return build_user_headers(contractor_id, ROLE_CONTRACTOR_ADMIN)


def make_client_manager_headers(client_id: str) -> dict:
    """Headers for one client's safety manager; X-User-ID is the Client id."""
    return build_user_headers(client_id, ROLE_CLIENT_SAFETY_MANAGER)


def make_analyst_headers(user_id: str = ANALYST_INSURANCE) -> dict:
    """Headers for an independent verifier; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_VERIFICATION_ANALYST)


def make_insurance_analyst_headers() -> dict:
    """The analyst identity that decides insurance certificates."""
    return make_analyst_headers(ANALYST_INSURANCE)


def make_statistics_analyst_headers() -> dict:
    """The analyst identity that verifies safety statistics."""
    return make_analyst_headers(ANALYST_STATISTICS)


def make_headers_with_role(user_id: str, role: str) -> dict:
    """Headers with an arbitrary role string, for authorization probes."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str = NETWORK_ADMIN_USER) -> dict:
    """Headers missing X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str = ROLE_NETWORK_ADMIN) -> dict:
    """Headers missing X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
