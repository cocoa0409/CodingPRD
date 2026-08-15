"""Pre-built role headers for every role in the PRD (§2.1).

BankTreasuryManager and BankOps are opaque identities: X-User-ID is not tied to
any persisted entity. CustomerAdmin, CustomerManager, CustomerDecisionMaker and
CustomerViewer are entity-backed by EnrollmentUser (X-User-ID must be the acting
EnrollmentUser's id). Ownership-gated calls MUST use the per-instance builders
with the real EnrollmentUser id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "bank_treasury_manager_headers": build_user_headers(
        "test-bank-mgr-1", "BankTreasuryManager"),
    "bank_ops_headers": build_user_headers("test-bank-ops-1", "BankOps"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "customer_admin_headers": build_user_headers("test-cust-admin-1", "CustomerAdmin"),
    "customer_manager_headers": build_user_headers("test-cust-mgr-1", "CustomerManager"),
    "customer_decision_maker_headers": build_user_headers(
        "test-cust-dm-1", "CustomerDecisionMaker"),
    "customer_viewer_headers": build_user_headers("test-cust-viewer-1", "CustomerViewer"),
}


def make_bank_treasury_manager_headers(user_id: str = "test-bank-mgr-1") -> dict:
    """For BankTreasuryManager (opaque). A specific user id only matters for the
    liability-case segregation-of-duties check (PRD §2.8)."""
    return build_user_headers(user_id, "BankTreasuryManager")


def make_bank_ops_headers(user_id: str = "test-bank-ops-1") -> dict:
    """For BankOps (opaque). A specific user id only matters for the
    liability-case segregation-of-duties check (PRD §2.8)."""
    return build_user_headers(user_id, "BankOps")


def make_customer_admin_headers(user_id: str) -> dict:
    """For CustomerAdmin (entity_backed:EnrollmentUser). Pass the acting
    EnrollmentUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustomerAdmin")


def make_customer_manager_headers(user_id: str) -> dict:
    """For CustomerManager (entity_backed:EnrollmentUser). Pass the acting
    EnrollmentUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustomerManager")


def make_customer_decision_maker_headers(user_id: str) -> dict:
    """For CustomerDecisionMaker (entity_backed:EnrollmentUser). Pass the acting
    EnrollmentUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustomerDecisionMaker")


def make_customer_viewer_headers(user_id: str) -> dict:
    """For CustomerViewer (entity_backed:EnrollmentUser). Pass the acting
    EnrollmentUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustomerViewer")
