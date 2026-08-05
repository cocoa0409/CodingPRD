"""Pre-built role headers for every role in the PRD.

Consumer is the only entity-backed role (X-User-ID == the acting Consumer.id),
so it also gets a per-instance builder. Every other role is opaque: a shared
constant header is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used verbatim by the design recipes.
REVIEWER_USER_ID = "rev-1"
FRAUD_ANALYST_1_ID = "fraud-1"
FRAUD_ANALYST_2_ID = "fraud-2"
PROGRAM_MANAGER_ID = "pm-1"
PLATFORM_ADMIN_ID = "admin-1"

TEST_USERS = {
    # Anonymous: X-User-ID is not required; a placeholder is harmless.
    "anonymous_headers": build_user_headers("anon", "Anonymous"),
    # Opaque roles — shared constant is the canonical form.
    "claim_reviewer_headers": build_user_headers(REVIEWER_USER_ID, "ClaimReviewer"),
    "fraud_analyst_1_headers": build_user_headers(FRAUD_ANALYST_1_ID, "FraudAnalyst"),
    "fraud_analyst_2_headers": build_user_headers(FRAUD_ANALYST_2_ID, "FraudAnalyst"),
    "program_manager_headers": build_user_headers(PROGRAM_MANAGER_ID, "ProgramManager"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    # entity_backed Consumer: shared constant is a fallback for non-ownership
    # tests only (e.g. 404/400 paths). Ownership-gated calls MUST use the
    # per-instance builder below with the real Consumer.id.
    "consumer_headers": build_user_headers("consumer-generic", "Consumer"),
}


def make_consumer_headers(user_id: str) -> dict:
    """For the Consumer role (entity_backed:Consumer). Pass the actual
    Consumer.id as user_id whenever the call is ownership-gated (filing,
    submitting, resubmitting, uploading documents, reading own resources)."""
    return build_user_headers(user_id, "Consumer")


def make_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "ClaimReviewer")


def make_fraud_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FraudAnalyst")
