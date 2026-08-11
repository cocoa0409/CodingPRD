"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "conflict_analyst_headers": build_user_headers("ca-1", "ConflictAnalyst"),
    "credential_analyst_headers": build_user_headers("cred-1", "CredentialAnalyst"),
    "billing_reviewer_headers": build_user_headers("br-1", "BillingReviewer"),
    # Expert is entity_backed: shared constant only for non-ownership-negative tests.
    "expert_headers": build_user_headers("no-such-expert", "Expert"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_case_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_conflict_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConflictAnalyst")


def make_credential_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CredentialAnalyst")


def make_billing_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingReviewer")


def make_expert_headers(user_id: str) -> dict:
    """For Expert (entity_backed: Expert). Pass the actual Expert.id as user_id
    whenever the call is ownership-gated (sign, counter, submit, revise,
    acknowledge, invoice submit/resubmit)."""
    return build_user_headers(user_id, "Expert")
