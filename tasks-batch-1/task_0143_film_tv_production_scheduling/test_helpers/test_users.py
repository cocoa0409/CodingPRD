"""Pre-built role headers for every role in the PRD.

Every role here is an opaque operator identifier: the server records X-User-ID
but never compares it to any entity's id when deciding ownership (PRD 2.1).
Authorization is decided purely by role, so shared constants are the canonical
form for all five roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "line_producer_headers": build_user_headers("test-line-producer-1", "LineProducer"),
    "first_ad_headers": build_user_headers("test-first-ad-1", "FirstAD"),
    "payroll_coordinator_headers": build_user_headers("test-payroll-1", "PayrollCoordinator"),
    "post_supervisor_headers": build_user_headers("test-post-supervisor-1", "PostSupervisor"),
    "union_rep_headers": build_user_headers("test-union-rep-1", "UnionRep"),
}
