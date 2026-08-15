"""Pre-built role headers for every role in the PRD.

Insured is entity-backed by Policy (X-User-ID is the acting Policy's id) and
Auditor is entity-backed by Auditor (X-User-ID is the acting Auditor's id);
ownership-gated calls MUST use the per-instance builders with the real entity
id. AuditManager, Underwriter, and BillingClerk are opaque identities whose
X-User-ID is never compared to any persisted entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only.
    "insured_headers": build_user_headers("test-insured-1", "Insured"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # opaque roles: shared constants are the canonical form.
    "audit_manager_headers": build_user_headers("mgr-1", "AuditManager"),
    "underwriter_headers": build_user_headers("uw-1", "Underwriter"),
    "billing_clerk_headers": build_user_headers("bill-1", "BillingClerk"),
}


def make_insured_headers(policy_id: str) -> dict:
    """For Insured (entity-backed by Policy). Pass the acting Policy.id
    whenever the call is ownership-gated."""
    return build_user_headers(policy_id, "Insured")


def make_auditor_headers(auditor_id: str) -> dict:
    """For Auditor (entity-backed by Auditor). Pass the acting Auditor.id
    whenever the call is ownership-gated."""
    return build_user_headers(auditor_id, "Auditor")


def make_audit_manager_headers(user_id: str = "mgr-1") -> dict:
    """For AuditManager (opaque). Use distinct user ids (e.g. mgr-1 vs mgr-2)
    where the segregation-of-duties rules require different operators."""
    return build_user_headers(user_id, "AuditManager")


def make_underwriter_headers(user_id: str = "uw-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_billing_clerk_headers(user_id: str = "bill-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")
