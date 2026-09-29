"""
Identities used by the test suite.

Two of the seven roles are entity backed: an Assured acts with the `X-User-ID`
of the open cover it holds, and a Surveyor acts with the `X-User-ID` of its own
surveyor record. Those identities therefore only exist once the corresponding
row has been created, so they are always built per test through
`make_assured_headers()` / `make_surveyor_headers()`. The remaining five roles
are opaque: any stable identifier is acceptable, so fixed header dicts are
provided for them.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

# --- role names, exactly as the API expects them in X-User-Role ---------
ROLE_UNDERWRITER = "Underwriter"
ROLE_ASSURED = "Assured"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_PREMIUM_AUDITOR = "PremiumAuditor"
ROLE_CLAIMS_ADJUSTER = "ClaimsAdjuster"
ROLE_SURVEYOR = "Surveyor"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_UNDERWRITER,
    ROLE_ASSURED,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PREMIUM_AUDITOR,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_SURVEYOR,
    ROLE_PLATFORM_ADMIN,
]

# --- opaque identities ---------------------------------------------------
UNDERWRITER_USER_ID = "underwriter-1"
UNDERWRITER_2_USER_ID = "underwriter-2"
COMPLIANCE_USER_ID = "compliance-1"
AUDITOR_USER_ID = "auditor-1"
AUDITOR_2_USER_ID = "auditor-2"
ADJUSTER_USER_ID = "adjuster-1"
ADJUSTER_2_USER_ID = "adjuster-2"
PLATFORM_ADMIN_USER_ID = "platform-1"

UNDERWRITER = build_user_headers(UNDERWRITER_USER_ID, ROLE_UNDERWRITER)
UNDERWRITER_2 = build_user_headers(UNDERWRITER_2_USER_ID, ROLE_UNDERWRITER)
COMPLIANCE_OFFICER = build_user_headers(COMPLIANCE_USER_ID, ROLE_COMPLIANCE_OFFICER)
PREMIUM_AUDITOR = build_user_headers(AUDITOR_USER_ID, ROLE_PREMIUM_AUDITOR)
PREMIUM_AUDITOR_2 = build_user_headers(AUDITOR_2_USER_ID, ROLE_PREMIUM_AUDITOR)
CLAIMS_ADJUSTER = build_user_headers(ADJUSTER_USER_ID, ROLE_CLAIMS_ADJUSTER)
CLAIMS_ADJUSTER_2 = build_user_headers(ADJUSTER_2_USER_ID, ROLE_CLAIMS_ADJUSTER)
PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)


# --- entity backed identities ------------------------------------------
def make_assured_headers(open_policy_id: str) -> Headers:
    """Headers for the assured holding the open cover `open_policy_id`."""
    return build_user_headers(open_policy_id, ROLE_ASSURED)


def make_surveyor_headers(surveyor_id: str) -> Headers:
    """Headers for the panel surveyor whose own record is `surveyor_id`."""
    return build_user_headers(surveyor_id, ROLE_SURVEYOR)


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary user identifier and role string."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Headers:
    """Headers that carry a role but no user identifier."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Headers:
    """Headers that carry a user identifier but no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
