"""Pre-built role headers for every role in the PRD (§2.1, §4)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (X-User-ID never compared to an
# entity id per PRD §2.1) and for Member-role calls that are not
# ownership-gated. For ownership-gated Member calls, use
# make_member_headers(member_id) with the actual Member.id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CoopAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "CoopRegistrar"),
    "accountant_headers": build_user_headers("test-accountant-1", "CoopAccountant"),
    "auditor_headers": build_user_headers("test-auditor-1", "ExternalAuditor"),
    "operator_headers": build_user_headers("test-operator-1", "ElevatorOperator"),
    "treasurer_headers": build_user_headers("test-treasurer-1", "CoopTreasurer"),
    "secretary_headers": build_user_headers("test-secretary-1", "BoardSecretary"),
    # Fallback for Member role — only for tests that never exercise ownership.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity-backed by Member). Pass the actual
    Member.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")
