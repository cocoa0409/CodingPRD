"""Pre-built role headers for every role in the PRD.

Shared constants are used for opaque roles (ProgramAdmin, HiringManager,
FinanceAnalyst) and for calls whose success does not depend on owning the
subject resource. Entity-backed roles (SupplierCoordinator, Worker) MUST be
built per instance via the make_*_headers builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "hiring_manager_headers": build_user_headers("hm-1", "HiringManager"),
    "finance_analyst_headers": build_user_headers("fin-1", "FinanceAnalyst"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # Entity-backed fallbacks — ONLY for tests that never pass an ownership
    # gate (e.g. forbidden-role probes). Never use for ownership-gated calls.
    "supplier_coordinator_headers": build_user_headers(
        "test-supplier-coordinator-1", "SupplierCoordinator"
    ),
    "worker_headers": build_user_headers("test-worker-1", "Worker"),
}


def make_supplier_coordinator_headers(supplier_id: str) -> dict:
    """SupplierCoordinator is entity-backed: X-User-ID is the Supplier id.

    Pass the actual supplier's id whenever the call is ownership-gated
    (offer respond, milestone deliver, worker registration).
    """
    return build_user_headers(supplier_id, "SupplierCoordinator")


def make_worker_headers(worker_id: str) -> dict:
    """Worker is entity-backed: X-User-ID is the Worker id.

    Pass the actual worker's id whenever the call is ownership-gated
    (timesheet create/submit on own assignments).
    """
    return build_user_headers(worker_id, "Worker")


def make_finance_analyst_headers(user_id: str) -> dict:
    """FinanceAnalyst is opaque, but invoice finalize/mark-paid record and
    compare the caller id (segregation of duties), so distinct named analysts
    are needed per test."""
    return build_user_headers(user_id, "FinanceAnalyst")


def make_hiring_manager_headers(user_id: str) -> dict:
    """HiringManager is opaque; a named manager is recorded as the actor on
    approvals/acceptances (approved_by_user_id, accepted_by_user_id)."""
    return build_user_headers(user_id, "HiringManager")
