"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# `Registrant` is the one entity-backed role: its X-User-ID must be the acting
# Account's id (PRD §2.1). The shared constant below is therefore ONLY safe for
# tests that never reach an ownership check (e.g. a 400-on-bad-payload probe).
# Every ownership-gated call must use make_registrant_headers(account["id"]).
#
# The other five roles are opaque operator identifiers, so the shared constants
# are the canonical form for them.
TEST_USERS = {
    "registrant_headers": build_user_headers("test-registrant-1", "Registrant"),
    "support_agent_headers": build_user_headers("support-1", "SupportAgent"),
    "abuse_analyst_headers": build_user_headers("analyst-1", "AbuseAnalyst"),
    "abuse_analyst_2_headers": build_user_headers("analyst-2", "AbuseAnalyst"),
    "billing_admin_headers": build_user_headers("billing-1", "BillingAdmin"),
    "platform_admin_headers": build_user_headers("platform-1", "PlatformAdmin"),
}


def make_registrant_headers(account_id: str) -> dict:
    """For the Registrant role, whose X-User-ID is the acting Account's id.

    Pass the real Account id whenever the call is ownership-gated.
    """
    return build_user_headers(account_id, "Registrant")


def make_abuse_analyst_headers(user_id: str) -> dict:
    """AbuseAnalyst headers for a named opaque operator (segregation of duties)."""
    return build_user_headers(user_id, "AbuseAnalyst")


def make_support_agent_headers(user_id: str = "support-1") -> dict:
    return build_user_headers(user_id, "SupportAgent")


def make_billing_admin_headers(user_id: str = "billing-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")


def make_platform_admin_headers(user_id: str = "platform-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def anonymous_headers() -> dict:
    """Anonymous is the one role permitted to omit X-User-ID (PRD §2.1)."""
    return {"X-User-Role": "Anonymous", "Content-Type": "application/json"}


def no_auth_headers() -> dict:
    """No X-User-Role at all — must draw ERR_UNAUTHENTICATED (PRD §2.1)."""
    return {"Content-Type": "application/json"}


ANONYMOUS = anonymous_headers()
SUPPORT = TEST_USERS["support_agent_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]
ANALYST_1 = TEST_USERS["abuse_analyst_headers"]
ANALYST_2 = TEST_USERS["abuse_analyst_2_headers"]
