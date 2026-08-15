"""Pre-built role headers for every role in the PRD.

SalesOpsAdmin, SalesOpsAnalyst, and RevOpsManager are opaque identities:
X-User-ID is not tied to any persisted entity (it is only recorded, e.g. as
created_by_user_id / decided_by_user_id). SalesRep is entity-backed by
SalesRep: X-User-ID IS the acting SalesRep's id, so ownership-gated calls
(submissions, disputes) MUST use make_sales_rep_headers with the real rep id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "SalesOpsAdmin"),
    "analyst_headers": build_user_headers("analyst-1", "SalesOpsAnalyst"),
    "manager_headers": build_user_headers("mgr-1", "RevOpsManager"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. wrong-role denial checks).
    "sales_rep_headers": build_user_headers("test-rep-1", "SalesRep"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """SalesOpsAdmin (opaque identity)."""
    return build_user_headers(user_id, "SalesOpsAdmin")


def make_analyst_headers(user_id: str = "analyst-1") -> dict:
    """SalesOpsAnalyst (opaque identity). Use a stable user_id when the test
    later needs the same creator identity (change-request cancel, self-approval)."""
    return build_user_headers(user_id, "SalesOpsAnalyst")


def make_manager_headers(user_id: str = "mgr-1") -> dict:
    """RevOpsManager (opaque identity). Use a stable user_id when the test
    asserts decided_by_user_id or segregation of duties."""
    return build_user_headers(user_id, "RevOpsManager")


def make_sales_rep_headers(rep_id: str) -> dict:
    """For SalesRep (entity_backed:SalesRep). Pass the acting SalesRep.id
    whenever the call is ownership-gated (submission create/withdraw,
    dispute create/withdraw)."""
    return build_user_headers(rep_id, "SalesRep")
