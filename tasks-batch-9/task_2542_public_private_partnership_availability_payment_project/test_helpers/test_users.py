"""Pre-built request headers for every role the PRD recognises.

For a caller whose role is `Concessionaire` the `X-User-ID` header is the
identifier of the Concessionaire row itself, so ownership-gated calls MUST use
`make_concessionaire_headers(concessionaire["id"])`. The remaining four roles are
opaque: their identifiers are free-form user ids, and the shared constants below
are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# --- Authority officer identities --------------------------------------------
# The PRD separates duties between officers on four pairs of operations, so the
# suite keeps several distinct officer identities available.
OFFICER_ALPHA = "officer-alpha"
OFFICER_BETA = "officer-beta"
OFFICER_GAMMA = "officer-gamma"
OFFICER_DELTA = "officer-delta"
OFFICER_EPSILON = "officer-epsilon"

PLATFORM_ADMIN_USER_ID = "admin-1"
LENDER_AGENT_USER_ID = "lender-1"
INDEPENDENT_CERTIFIER_USER_ID = "certifier-1"


TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "authority_officer_headers": build_user_headers(OFFICER_ALPHA, "AuthorityOfficer"),
    "officer_alpha_headers": build_user_headers(OFFICER_ALPHA, "AuthorityOfficer"),
    "officer_beta_headers": build_user_headers(OFFICER_BETA, "AuthorityOfficer"),
    "officer_gamma_headers": build_user_headers(OFFICER_GAMMA, "AuthorityOfficer"),
    "officer_delta_headers": build_user_headers(OFFICER_DELTA, "AuthorityOfficer"),
    "officer_epsilon_headers": build_user_headers(OFFICER_EPSILON, "AuthorityOfficer"),
    "lender_agent_headers": build_user_headers(LENDER_AGENT_USER_ID, "LenderAgent"),
    "independent_certifier_headers": build_user_headers(
        INDEPENDENT_CERTIFIER_USER_ID, "IndependentCertifier"
    ),
    # Fallback only for tests that never reach an ownership comparison.
    "concessionaire_headers": build_user_headers("concessionaire-unknown", "Concessionaire"),
}

# Headers carrying no identity at all, for the unauthenticated path.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_concessionaire_headers(concessionaire_id: str) -> dict:
    """Headers for the `Concessionaire` role. Pass the Concessionaire row's own id."""
    return build_user_headers(concessionaire_id, "Concessionaire")


def make_authority_officer_headers(user_id: str) -> dict:
    """Headers for the `AuthorityOfficer` role under a chosen officer identity."""
    return build_user_headers(user_id, "AuthorityOfficer")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_lender_agent_headers(user_id: str = LENDER_AGENT_USER_ID) -> dict:
    return build_user_headers(user_id, "LenderAgent")


def make_independent_certifier_headers(
    user_id: str = INDEPENDENT_CERTIFIER_USER_ID,
) -> dict:
    return build_user_headers(user_id, "IndependentCertifier")


def make_headers_with_role(user_id: str, role: str) -> dict:
    """Escape hatch for role-gate tests that need an arbitrary role string."""
    return build_user_headers(user_id, role)
