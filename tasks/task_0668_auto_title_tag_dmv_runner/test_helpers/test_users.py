"""Pre-built role headers for every role in the PRD.

Five roles (PlatformAdmin, IntakeClerk, FeeAnalyst, RunnerDispatcher, LienOfficer)
carry an opaque X-User-ID that is never compared to any entity id, so a shared
constant is the canonical form for them. AccountHolder's X-User-ID is the id of the
acting Account, so ownership-gated calls MUST use make_account_holder_headers(account_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque operator roles use these directly. The AccountHolder
# shared constant is a fallback for non-ownership tests only (e.g. role-denial,
# not-found): a fixed string never equals a real Account.id, so any ownership-gated
# AccountHolder call must use the per-instance builder below.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "intake_clerk_headers": build_user_headers("clerk-1", "IntakeClerk"),
    "fee_analyst_headers": build_user_headers("analyst-1", "FeeAnalyst"),
    "runner_dispatcher_headers": build_user_headers("dispatcher-1", "RunnerDispatcher"),
    "lien_officer_headers": build_user_headers("lien-officer-1", "LienOfficer"),
    "account_holder_headers": build_user_headers("account-holder-unowned", "AccountHolder"),
}


def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity_backed:Account). Pass the actual Account.id as the
    X-User-ID whenever the call is ownership-gated (transaction cancel, payments)."""
    return build_user_headers(account_id, "AccountHolder")


def make_intake_clerk_headers(user_id: str) -> dict:
    """IntakeClerk is opaque; this builder lets a test stamp a specific submitting
    user id (e.g. to exercise segregation-of-duties)."""
    return build_user_headers(user_id, "IntakeClerk")


def make_lien_officer_headers(user_id: str) -> dict:
    """LienOfficer is opaque; this builder lets a test stamp a specific perfecting
    user id (e.g. to make it equal/differ from the submitting clerk)."""
    return build_user_headers(user_id, "LienOfficer")
