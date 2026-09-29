"""Identity headers for every role the API recognises.

Provider and Substitute identities are entity backed: their ``X-User-ID`` must
resolve to a stored row, so headers for those roles are built per entity id.
The remaining roles are opaque operator identities.
"""

from prd_bench_local_runner.testing import build_user_headers

from test_helpers.types import UserRole

NETWORK_ADMIN_USER_ID = "admin-1"
FISCAL_OFFICER_USER_ID = "fiscal-1"
COACH_A_USER_ID = "coach-a"
COACH_B_USER_ID = "coach-b"

# Sent when the caller presents no identity at all. Only the provider
# application endpoint is exempt from the header checks.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

NETWORK_ADMIN_HEADERS = build_user_headers(NETWORK_ADMIN_USER_ID, UserRole.NETWORK_ADMIN.value)
FISCAL_OFFICER_HEADERS = build_user_headers(FISCAL_OFFICER_USER_ID, UserRole.FISCAL_OFFICER.value)
COACH_A_HEADERS = build_user_headers(COACH_A_USER_ID, UserRole.QUALITY_COACH.value)
COACH_B_HEADERS = build_user_headers(COACH_B_USER_ID, UserRole.QUALITY_COACH.value)


def make_provider_headers(provider_id: str) -> dict:
    """Headers for a Provider acting as the home identified by ``provider_id``."""
    return build_user_headers(provider_id, UserRole.PROVIDER.value)


def make_substitute_headers(substitute_id: str) -> dict:
    """Headers for a Substitute acting as the pool member ``substitute_id``."""
    return build_user_headers(substitute_id, UserRole.SUBSTITUTE.value)


def make_coach_headers(user_id: str) -> dict:
    """Headers for a QualityCoach acting under the operator id ``user_id``."""
    return build_user_headers(user_id, UserRole.QUALITY_COACH.value)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary role / identity pair."""
    return build_user_headers(user_id, role)


TEST_USERS = {
    "no_auth_headers": NO_AUTH_HEADERS,
    "network_admin_headers": NETWORK_ADMIN_HEADERS,
    "fiscal_officer_headers": FISCAL_OFFICER_HEADERS,
    "coach_a_headers": COACH_A_HEADERS,
    "coach_b_headers": COACH_B_HEADERS,
}
