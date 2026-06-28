"""Pre-built role headers for every role in the PRD (§2.1).

All four roles carry an OPAQUE identity (PRD §2.1): X-User-ID is an operator/party
identifier and is never the primary key of a persisted entity. For a Policyholder the
acting X-User-ID is captured as Policy.policyholder_id at creation and later compared
against the request's X-User-ID for owner-scoped writes — so ownership tests must reuse
the SAME X-User-ID that created the policy. The make_policyholder_headers() builder
exists for that purpose.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The default Policyholder id "ph-1" is used by all fixtures that
# create a policy, so reusing it for that policy's owner-scoped writes preserves ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "underwriter_headers": build_user_headers("uw-1", "UnderwritingAgent"),
    "policyholder_headers": build_user_headers("ph-1", "Policyholder"),
    "adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
}


def make_policyholder_headers(user_id: str) -> dict:
    """Build Policyholder headers carrying a specific X-User-ID.

    Pass the same id that created the policy (default "ph-1") for owner-scoped writes
    (pay, cancel, resubmit, attach document); pass a different id to exercise the
    ERR_NOT_POLICY_OWNER guard.
    """
    return build_user_headers(user_id, "Policyholder")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UnderwritingAgent")


def make_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")
