"""Pre-built role headers for every role in the PRD (§2.1).

All five roles carry an OPAQUE identity (PRD §2.1): the X-User-ID header is never
compared to any entity id and ownership is never derived from it. Shared constants
are therefore the canonical form for every role; no per-instance entity-backed
builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "merchandiser_headers": build_user_headers("test-merchandiser-1", "Merchandiser"),
    "grade_clerk_headers": build_user_headers("test-gradeclerk-1", "GradeClerk"),
    "settlement_officer_headers": build_user_headers("test-settlementofficer-1", "SettlementOfficer"),
    "shipping_clerk_headers": build_user_headers("test-shippingclerk-1", "ShippingClerk"),
    "risk_manager_headers": build_user_headers("test-riskmanager-1", "RiskManager"),
}
