"""Pre-built role headers for every role in the PRD.

Two roles: StaffManager (opaque operator id) and Member (entity_backed:Member).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - StaffManager: opaque identifier, never compared to any entity id -> shared constant is canonical.
#  - Member: shared constant is a fallback for non-ownership tests (e.g. 401/404) only; ownership-gated
#    calls MUST use make_member_headers(member_id) with the real Member.id.
TEST_USERS = {
    "staff_headers": build_user_headers("staff-operator-1", "StaffManager"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (booking for self, paying own dues, etc.)."""
    return build_user_headers(user_id, "Member")


def make_staff_headers(user_id: str = "staff-operator-1") -> dict:
    """For the StaffManager role (opaque). The id is recorded for audit but never compared."""
    return build_user_headers(user_id, "StaffManager")
