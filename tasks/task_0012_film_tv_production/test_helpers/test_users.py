"""Pre-built role headers for every role in the PRD (§2.1).

PRD §2.1 — "For every role in this system, the value of `X-User-ID` is an opaque
operator identifier and is **not** the primary key of any entity stored by the
API." All five roles are opaque, so the shared TEST_USERS constants are
canonical for *role authorization* checks.

X-User-ID values still matter for two pathways:

1. ChangeOrder segregation-of-duties: PRD §3.7 — "the approver's `X-User-ID` is
   *not* equal to `requested_by`". Tests of that rule must use distinct
   X-User-IDs for the requesting LineProducer and the approving FinanceController
   — the per-instance helpers (make_line_producer_headers / make_finance_controller_headers)
   are how to do that.
2. Audit-log attribution: AuditLog.actor_user_id, EquipmentEvent.actor_user_id,
   and CrewAssignment.crew_user_id are recorded directly from X-User-ID for
   audit purposes (no ownership check). Tests that assert on those recorded
   values can use either pathway.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for opaque roles.
TEST_USERS = {
    "executive_producer_headers": build_user_headers("test-exec-producer-001", "ExecutiveProducer"),
    "line_producer_headers": build_user_headers("test-line-producer-001", "LineProducer"),
    "finance_controller_headers": build_user_headers("test-finance-controller-001", "FinanceController"),
    "casting_director_headers": build_user_headers("test-casting-director-001", "CastingDirector"),
    "production_coordinator_headers": build_user_headers("test-production-coordinator-001", "ProductionCoordinator"),
}


# --- Per-instance builders ---
# Use these whenever a test must distinguish between two principals of the same
# role (e.g., the LineProducer who submitted a change order vs. the
# FinanceController who approves it must be different X-User-IDs; or two
# distinct FinanceControllers in a segregation-of-duties scenario).

def make_executive_producer_headers(user_id: str = "test-exec-producer-001") -> dict:
    return build_user_headers(user_id, "ExecutiveProducer")


def make_line_producer_headers(user_id: str = "test-line-producer-001") -> dict:
    return build_user_headers(user_id, "LineProducer")


def make_finance_controller_headers(user_id: str = "test-finance-controller-001") -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_casting_director_headers(user_id: str = "test-casting-director-001") -> dict:
    return build_user_headers(user_id, "CastingDirector")


def make_production_coordinator_headers(user_id: str = "test-production-coordinator-001") -> dict:
    return build_user_headers(user_id, "ProductionCoordinator")


def with_override_reason(headers: dict, reason: str = "Test override") -> dict:
    """Return a copy of headers with X-Override-Reason set (PRD §2.6, §3.7, §3.9)."""
    out = dict(headers)
    out["X-Override-Reason"] = reason
    return out
