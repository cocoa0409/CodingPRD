"""Pre-built role headers for every role in the PRD.

Identity semantics (PRD section "User and Role-Based Access Control"):
- Operator is entity-backed: X-User-ID must be the acting Operator record's id
  for any ownership-gated call. Use make_operator_headers(operator_id) for
  those; the shared constant is only for calls that never touch an
  ownership-checked resource.
- SchedulingOfficer, PayrollClerk, UnionRep are opaque staff identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "scheduling_officer_headers": build_user_headers("test-sched-officer-1", "SchedulingOfficer"),
    # Fallback only for Operator calls that are not ownership-gated (rare).
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "payroll_clerk_headers": build_user_headers("test-payroll-clerk-1", "PayrollClerk"),
    "union_rep_headers": build_user_headers("test-union-rep-1", "UnionRep"),
}


def make_operator_headers(user_id: str) -> dict:
    """For the entity-backed Operator role. Pass the real Operator.id as
    user_id whenever the call is ownership-gated (submitting/withdrawing own
    bid entries, disputing pay on own assignments, withdrawing own grievances,
    reporting own absence)."""
    return build_user_headers(user_id, "Operator")


def make_scheduling_officer_headers(user_id: str = "test-sched-officer-1") -> dict:
    return build_user_headers(user_id, "SchedulingOfficer")


def make_payroll_clerk_headers(user_id: str = "test-payroll-clerk-1") -> dict:
    return build_user_headers(user_id, "PayrollClerk")


def make_union_rep_headers(user_id: str = "test-union-rep-1") -> dict:
    return build_user_headers(user_id, "UnionRep")
