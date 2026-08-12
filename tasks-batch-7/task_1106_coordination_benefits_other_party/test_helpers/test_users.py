"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the six opaque roles (PRD §2.1: their X-User-ID
# is never compared to any entity id) and for MemberSelf only in tests whose
# success does not depend on ownership (e.g. 404 / 400 / RBAC-denial paths).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "eligibility_analyst_headers": build_user_headers("test-elig-1", "EligibilityAnalyst"),
    "cob_analyst_headers": build_user_headers("test-cob-1", "COBAnalyst"),
    "claims_examiner_headers": build_user_headers("test-examiner-1", "ClaimsExaminer"),
    "recovery_specialist_headers": build_user_headers("test-recovery-1", "RecoverySpecialist"),
    "cob_auditor_headers": build_user_headers("test-auditor-1", "COBAuditor"),
    "member_self_headers": build_user_headers("test-member-1", "MemberSelf"),
}


def make_member_self_headers(user_id: str) -> dict:
    """For MemberSelf (entity_backed: Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (PRD §2.1: ownership checks
    compare the resource's member foreign-key field to X-User-ID)."""
    return build_user_headers(user_id, "MemberSelf")
