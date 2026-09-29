"""Acting identities and their request headers.

Every request carries `X-User-ID` and `X-User-Role`. Four of the six roles are
resolved against a stored row - the three assessor roles resolve against an
assessor and the scanning-vendor role against an ASV vendor - so their headers
must always be built from the identifier the API actually minted. The two
remaining roles are opaque operators and may use a fixed identifier.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ASSESSOR,
    ROLE_ASV_VENDOR,
    ROLE_CLIENT_REPRESENTATIVE,
    ROLE_LEAD_ASSESSOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_QA_REVIEWER,
)

# Opaque actors: the platform operator and the client's own representative are
# not backed by a registry row, so a stable identifier is enough for them.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "role": ROLE_PLATFORM_ADMIN,
    },
    "client_representative": {
        "user_id": "22222222-2222-4222-8222-222222222222",
        "role": ROLE_CLIENT_REPRESENTATIVE,
    },
}

UNKNOWN_ACTOR_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build the two identity headers for an arbitrary actor."""
    return build_user_headers(user_id, role)


def make_lead_headers(user_id: str) -> Dict[str, str]:
    """Headers for the lead assessor of an engagement.

    `user_id` must be the assessor identifier the roster returned, because
    lead-only operations compare it against the engagement's lead_assessor_id.
    """
    return build_user_headers(user_id, ROLE_LEAD_ASSESSOR)


def make_assessor_headers(user_id: str) -> Dict[str, str]:
    """Headers for a staff assessor, resolved against the assessor roster."""
    return build_user_headers(user_id, ROLE_ASSESSOR)


def make_qa_reviewer_headers(user_id: str) -> Dict[str, str]:
    """Headers for the quality-assurance reviewer of an engagement.

    Reviewer-only operations compare this identifier against the engagement's
    qa_reviewer_id, so it must be the nominated assessor's identifier.
    """
    return build_user_headers(user_id, ROLE_QA_REVIEWER)


def make_asv_vendor_headers(user_id: str) -> Dict[str, str]:
    """Headers for a scanning vendor, resolved against the vendor registry.

    Vendor-only operations compare this identifier against the scan cycle's
    asv_vendor_id, so it must be the registered vendor's identifier.
    """
    return build_user_headers(user_id, ROLE_ASV_VENDOR)


def make_client_representative_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for the client's representative, an opaque actor."""
    resolved = user_id or TEST_USERS["client_representative"]["user_id"]
    return build_user_headers(resolved, ROLE_CLIENT_REPRESENTATIVE)


def make_platform_admin_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for the platform operator, an opaque actor."""
    resolved = user_id or TEST_USERS["platform_admin"]["user_id"]
    return build_user_headers(resolved, ROLE_PLATFORM_ADMIN)


def admin_headers() -> Dict[str, str]:
    """Shorthand for the platform operator's headers."""
    return make_platform_admin_headers()


def client_rep_headers() -> Dict[str, str]:
    """Shorthand for the client representative's headers."""
    return make_client_representative_headers()


def headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Build headers for any role, defaulting the opaque actors' identifiers."""
    if role in (ROLE_LEAD_ASSESSOR, ROLE_ASSESSOR, ROLE_QA_REVIEWER, ROLE_ASV_VENDOR):
        if not user_id:
            raise ValueError(
                "role %s resolves against a stored row and needs a real id" % role
            )
        return build_user_headers(user_id, role)
    if role == ROLE_CLIENT_REPRESENTATIVE:
        return make_client_representative_headers(user_id)
    if role == ROLE_PLATFORM_ADMIN:
        return make_platform_admin_headers(user_id)
    raise ValueError("unknown role %s" % role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that name a role but carry no `X-User-ID` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_user(role: str) -> Dict[str, str]:
    """Headers whose `X-User-ID` resolves to no assessor, vendor or operator."""
    return build_user_headers(UNKNOWN_ACTOR_ID, role)
