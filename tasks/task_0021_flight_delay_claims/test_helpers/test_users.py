"""Pre-built role headers for every role in the PRD.

PRD §2.1 explicitly states that every role uses **opaque** user identifiers:
"the value of X-User-ID is an operator identifier that is not tied to any
persisted entity. The server records it where a state-machine transition
explicitly demands it (for example, as assigned_reviewer_id,
assigned_approver_id, payout_operator_id, assigned_batch_approver_id, or
assigned_batch_executor_id) but does not compare it against any entity's id."

Because identity is opaque for all roles, shared TEST_USERS constants are
canonical for any test that does not need DISTINCT users to satisfy
segregation-of-duties (§2.1, §3.4, §3.8, §3.9). Whenever SoD applies — a
reviewer cannot also approve, an approver cannot also be the payout
operator/batch approver, a batch approver cannot also be the batch executor —
fixtures and tests must use the per-instance builder make_<role>_headers(uid)
with a freshly minted operator id so the subsequent SoD check passes (or
deliberately fails when negative-testing SoD).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not require
# distinct users to satisfy segregation-of-duties.
TEST_USERS = {
    "claims_admin_headers": build_user_headers("test-claims-admin-1", "ClaimsAdmin"),
    "policy_admin_headers": build_user_headers("test-policy-admin-1", "PolicyAdmin"),
    "claims_reviewer_headers": build_user_headers("test-reviewer-1", "ClaimsReviewer"),
    "claims_approver_headers": build_user_headers("test-approver-1", "ClaimsApprover"),
    "batch_approver_headers": build_user_headers("test-batch-approver-1", "BatchApprover"),
    "batch_executor_headers": build_user_headers("test-batch-executor-1", "BatchExecutor"),
    "payout_operator_headers": build_user_headers("test-payout-op-1", "PayoutOperator"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "system_headers": build_user_headers("test-system-1", "system"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


# --- Per-instance builders ---
# Identity is opaque for all roles, so these builders simply mint headers with
# a user-supplied operator id. Use them whenever SoD requires distinct ids.

def make_claims_admin_headers(user_id: str = "test-claims-admin-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdmin")


def make_policy_admin_headers(user_id: str = "test-policy-admin-1") -> dict:
    return build_user_headers(user_id, "PolicyAdmin")


def make_claims_reviewer_headers(user_id: str) -> dict:
    """ClaimsReviewer headers. Pass a distinct user_id whenever the test uses
    submit_review / return_to_match — the server records the value as
    assigned_reviewer_id and SoD later compares it against the approver."""
    return build_user_headers(user_id, "ClaimsReviewer")


def make_claims_approver_headers(user_id: str) -> dict:
    """ClaimsApprover headers. PRD §3.4: the approver's X-User-ID must differ
    from the claim's assigned_reviewer_id (otherwise ERR_SOD_VIOLATION)."""
    return build_user_headers(user_id, "ClaimsApprover")


def make_batch_approver_headers(user_id: str) -> dict:
    """BatchApprover headers. PRD §3.8: the batch approver's X-User-ID must
    differ from every per-claim assigned_approver_id in the batch."""
    return build_user_headers(user_id, "BatchApprover")


def make_batch_executor_headers(user_id: str) -> dict:
    """BatchExecutor headers. PRD §3.9: the executor's X-User-ID must differ
    from the recorded assigned_batch_approver_id."""
    return build_user_headers(user_id, "BatchExecutor")


def make_payout_operator_headers(user_id: str) -> dict:
    """PayoutOperator headers. PRD §3.9: the operator's X-User-ID cannot equal
    the per-claim assigned_approver_id."""
    return build_user_headers(user_id, "PayoutOperator")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_system_headers(user_id: str = "test-system-1") -> dict:
    return build_user_headers(user_id, "system")


def make_any_headers(user_id: str = "test-any-1") -> dict:
    return build_user_headers(user_id, "Any")
