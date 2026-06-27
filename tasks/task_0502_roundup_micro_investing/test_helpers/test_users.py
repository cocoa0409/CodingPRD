"""Pre-built role headers for every role in the PRD.

PlatformAdmin and Anonymous are opaque-identity: X-User-ID is an opaque
identifier never compared to any entity, so the shared constant is canonical.

Investor and CustodialGuardian are entity-backed (their X-User-ID must equal
the acting Account's id for ownership checks to pass). Ownership-gated calls
MUST use make_investor_headers(account_id) / make_guardian_headers(account_id)
with the real Account.id — never the shared fallback constant, which would
fail every ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # Entity-backed fallbacks: safe ONLY for non-ownership tests (e.g. 404/403
    # role checks). Ownership-gated calls must use the builders below.
    "investor_headers": build_user_headers("investor-fallback-1", "Investor"),
    "custodial_guardian_headers": build_user_headers("guardian-fallback-1", "CustodialGuardian"),
}


def make_investor_headers(account_id: str) -> dict:
    """For Investor (entity_backed:Account). Pass the actual Account.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Investor")


def make_guardian_headers(account_id: str) -> dict:
    """For CustodialGuardian (entity_backed:Account). Pass the actual Account.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "CustodialGuardian")


def make_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


def make_anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
