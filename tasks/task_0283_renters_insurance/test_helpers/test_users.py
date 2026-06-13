"""Pre-built role headers for every role in the Renters Insurance API.

- Underwriter and ClaimsAdjuster identities are opaque operator ids: the
  shared constants below are the canonical form.
- Policyholder identity is entity-backed: X-User-ID must be the acting
  Policyholder entity's id. For ownership-gated calls, fixtures MUST build
  headers via make_policyholder_headers(policyholder_id); the shared constant
  is a fallback only for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    # Second opaque underwriter id — used where two distinct operators are needed.
    "underwriter_headers_2": build_user_headers("test-underwriter-2", "Underwriter"),
    "adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    # Second opaque adjuster id — for segregation-of-duties style scenarios.
    "adjuster_headers_2": build_user_headers("test-adjuster-2", "ClaimsAdjuster"),
    # Fallback policyholder constant — only for non-ownership tests.
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
}


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    """Underwriter (opaque). Any stable operator id is acceptable."""
    return build_user_headers(user_id, "Underwriter")


def make_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    """ClaimsAdjuster (opaque). Any stable operator id is acceptable."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_policyholder_headers(user_id: str) -> dict:
    """Policyholder (entity_backed:Policyholder). Pass the actual Policyholder.id
    as user_id whenever the call is ownership-gated (filing claims, adding items,
    paying invoices, naming additional insureds, reading own resources)."""
    return build_user_headers(user_id, "Policyholder")
