"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator capacities: X-User-ID is an opaque operator
identifier with no ownership relationship to any stored record (PRD Section 2.1).
Authorization is decided purely from the role, never from an X-User-ID match, so
the shared constants below are the canonical form for every test.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "quality_manager_headers": build_user_headers("test-qm-1", "QualityManager"),
    "receiving_clerk_headers": build_user_headers("test-clerk-1", "ReceivingClerk"),
    "production_operator_headers": build_user_headers("test-op-1", "ProductionOperator"),
    "safety_auditor_headers": build_user_headers("test-auditor-1", "SafetyAuditor"),
}
